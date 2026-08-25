# Supabase Migration Workflow

Shared project ref: `bgjapctiawosgpjcyfuq`

This folder is the non-destructive migration source for Re:mind. The remote
project is the source of truth, so pull before pushing whenever credentials are
available.

```bash
npx supabase login
npx supabase link --project-ref bgjapctiawosgpjcyfuq
npx supabase db pull
npx supabase db push
```

Do not run `supabase db reset` against the shared project. Apply migrations only
after reviewing the pending SQL summary. Real counseling data must not be stored
until auth, RLS, audit logging, and retention policy are implemented.
