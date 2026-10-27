-- First create the HTS login user under Authentication > Users.
-- Replace the placeholder with that user's UUID (not the project ID).
-- Run this separately from 001_chart_analysis.sql.
begin;

insert into public.hts_editors(user_id)
values ('a14a49e6-fbe9-46e9-891a-8c49c5173b45'::uuid)
on conflict (user_id) do nothing;

commit;
