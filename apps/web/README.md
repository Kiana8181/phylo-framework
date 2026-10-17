# Web application

The Next.js front end of Phylo-Framework. It is built and run as part of the
whole application; see the [root README](../../README.md) for how to start it
and [docs/DEVELOPMENT.md](../../docs/DEVELOPMENT.md) for the development modes.

- Pages are under `app/(site)/`: the landing page, sign-in (`/auth`), the
  dashboard with the run wizard, run history, comparison and files, and the
  user documentation (`/documents`).
- Forms for each method are generated from its contract in
  `packages/contracts`; there is no per-method form code.
- The address of the API is `NEXT_PUBLIC_API_BASE_URL`. It is compiled into the
  bundle, so the image must be rebuilt after changing it.

From the repository root:

```bash
npm run dev:web                 # development server on the host (needs .env and a running API)
npm -w web run test             # unit and component tests
npm -w web exec tsc -- --noEmit # type check
npm run lint
npm -w web run build            # production build
```

The browser tests (`tests/browser`, Playwright) run against the full test
stack: `npm run test:all`.
