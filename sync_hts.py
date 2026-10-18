"""Export chart data only; exclude credentials and personal memos."""
import json
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parent

def sync():
    source = ROOT.parent / "my_hts/data"
    watch = json.loads((source / "watchlist.json").read_text(encoding="utf-8"))
    stocks = {s["code"]:s["name"] for s in watch["items"]}
    stocks["424870"] = "이뮨온시아"
    drawings = {}
    for path in sorted((source / "drawings").glob("*.json")):
        if len(path.stem) != 6 or not path.stem.isdigit():
            continue
        drawings[path.stem] = json.loads(path.read_text(encoding="utf-8"))
        stocks.setdefault(path.stem,path.stem)
    snapshot = {"exported_at":datetime.now(timezone.utc).isoformat(), "stocks":[{"code":c,"name":n} for c,n in sorted(stocks.items())],"drawings":drawings}
    (ROOT / "data").mkdir(exist_ok=True)
    (ROOT / "data/hts_snapshot.json").write_text(json.dumps(snapshot,ensure_ascii=False,indent=2),encoding="utf-8")
    print(f"Exported {len(stocks)} symbols and {len(drawings)} drawing files")

if __name__ == "__main__":
    sync()
