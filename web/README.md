# Frontend integration point

Add the React/Vite app here. The current container serves a small FastAPI status page.
Once the frontend is ready, add a Node build stage to `Dockerfile`, copy `web/dist`
into the image, and mount it in FastAPI *after* the API routes. Add `npm ci` and
`npm run build` to CI. Use relative `/api/v1/...` URLs so one deployment serves both.

No API keys, database URLs, or AWS credentials belong in browser code or `VITE_*` variables.
