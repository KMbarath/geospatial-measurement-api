# Submission Checklist

Use this checklist immediately before sharing the project.

## Repository and delivery

- [ ] Create a **public** GitHub repository.
- [ ] Add the remote, commit the final changes, and push the `main` branch.
- [ ] Open the GitHub URL in an incognito/private browser window to confirm it is publicly visible.
- [ ] Share the repository URL in the requested submission channel.
- [ ] Confirm no secrets, local database files, uploaded files, virtual environments, or `.env` files were committed.

## Functional verification

- [ ] Create a clean virtual environment and run `pip install -r requirements-dev.txt`.
- [ ] Run `pytest -q`; all 39 tests should pass.
- [ ] Start the app with `uvicorn app.main:app --reload`.
- [ ] Open `http://127.0.0.1:8000/` and upload `samples/survey.kml`.
- [ ] Verify that the upload is `COMPLETED`, five features are listed, and both area and length results appear.
- [ ] Upload `samples/plot_utm43n.zip` and `samples/parcels_wgs84.zip`.
- [ ] Open `/docs` and confirm the documented API is available.

## Reviewer readiness

- [ ] Verify the README describes local setup, endpoints, architecture, processing and CRS flows, design decisions, learnings, and future scope.
- [ ] Ensure the sample files remain in `samples/`.
- [ ] Check that the browser dashboard at `/` and Swagger documentation at `/docs` both load.
- [ ] Review the GitHub repository root for clear naming and no unrelated files.
