"""Generate Kakao entity CSV: no header, entry then one synonym per column.

Uses data/krx_listing.csv; --refresh downloads a new KRX listing via FDR.
"""
import argparse
import csv
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def export(refresh=False, refresh_etf=False):
    listing = ROOT / "data/krx_listing.csv"
    if refresh:
        import requests
        import FinanceDataReader as fdr
        original = requests.sessions.Session.request
        def bounded(self, method, url, **kwargs):
            kwargs.setdefault("timeout", 20)
            return original(self, method, url, **kwargs)
        requests.sessions.Session.request = bounded
        try:
            df = fdr.StockListing("KRX")
        finally:
            requests.sessions.Session.request = original
        if len(df) < 1000:
            raise ValueError("Incomplete KRX listing; existing file was not overwritten")
        listing.parent.mkdir(exist_ok=True)
        df[["Code", "Name", "Market"]].to_csv(listing, index=False, encoding="utf-8")
    etf_listing = ROOT / "data/etf_listing.csv"
    if refresh or refresh_etf:
        import requests
        response = requests.get("https://finance.naver.com/api/sise/etfItemList.nhn", timeout=(3, 20))
        response.raise_for_status()
        etfs = response.json()["result"]["etfItemList"]
        if not etfs:
            raise ValueError("Empty ETF listing; existing file was not overwritten")
        with etf_listing.open("w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["Code", "Name", "Market"])
            writer.writerows((e["itemcode"], e["itemname"], "ETF") for e in etfs)
    with listing.open(encoding="utf-8-sig", newline="") as f:
        stocks = list(csv.DictReader(f))
    if etf_listing.exists():
        with etf_listing.open(encoding="utf-8-sig", newline="") as f:
            stocks.extend(csv.DictReader(f))
    if len({s["Code"] for s in stocks}) != len(stocks):
        raise ValueError("Duplicate stock/ETF codes")
    aliases = json.loads((ROOT / "data/stock_aliases.json").read_text(encoding="utf-8"))
    brands = {"KODEX": "코덱스", "TIGER": "타이거", "ACE": "에이스",
              "RISE": "라이즈", "SOL": "솔", "PLUS": "플러스", "HANARO": "하나로",
              "KOSEF": "코세프", "KIWOOM": "키움", "TIMEFOLIO": "타임폴리오"}
    aliases = {code: list(values) for code, values in aliases.items()}
    for s in stocks:
        if s["Market"] == "ETF":
            brand, sep, rest = s["Name"].partition(" ")
            if sep and brand.upper() in brands:
                aliases.setdefault(s["Code"], []).append(brands[brand.upper()] + " " + rest)
    names = [" ".join(s["Name"].split()) for s in stocks]
    if len(set(names)) != len(names):
        raise ValueError("Duplicate canonical names require manual resolution")
    normalize = lambda value: "".join(value.split()).casefold()
    owners = {}
    for s, name in zip(stocks, names):
        for value in (name, s["Code"], *aliases.get(s["Code"], [])):
            owners.setdefault(normalize(value), set()).add(s["Code"])
    used = {normalize(n) for n in names}
    rows = []
    catalog = []
    for s, name in sorted(zip(stocks, names), key=lambda item: item[0]["Code"]):
        synonyms = [s["Code"]]
        for alias in aliases.get(s["Code"], []):
            key = normalize(alias)
            if len(owners[key]) == 1 and key not in used:
                synonyms.append(alias)
                used.add(key)
        if len(synonyms) > 6:
            raise ValueError(f"Too many synonyms for {name}")
        rows.append([name, *synonyms, *([""] * (6-len(synonyms)))])
        catalog.append({"code": s["Code"], "name": name, "aliases": synonyms[1:]})
    output = ROOT / "data/stock_name_all.csv"
    with output.open("w", encoding="utf-8", newline="") as f:
        csv.writer(f).writerows(rows)
    with output.open(encoding="utf-8", newline="") as f:
        actual = list(csv.reader(f))
    assert actual == rows and all(len(row) == 7 for row in actual)
    (ROOT / "data/stock_catalog.json").write_text(
        json.dumps(catalog, ensure_ascii=False, indent=2), encoding="utf-8")
    metadata = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": "FinanceDataReader KRX listing + Naver ETF listing",
        "source_files": ["krx_listing.csv", "etf_listing.csv"], "entries": len(rows),
        "markets": dict(Counter(s["Market"] for s in stocks)),
        "format": "UTF-8 CSV, no header; column 1 entry, columns 2-7 synonyms",
        "scope": "KRX stocks including preferred shares/SPACs and domestic-listed ETFs; excludes ETNs",
    }
    (ROOT / "data/stock_name_all.meta.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(metadata, ensure_ascii=True))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--refresh-etf", action="store_true")
    args = parser.parse_args()
    export(args.refresh, args.refresh_etf)
