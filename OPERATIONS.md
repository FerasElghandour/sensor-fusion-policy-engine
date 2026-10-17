# Operating scope and release procedure

**Feras Elghandour**

## Public demonstration

The hosted report is a static site served over GitHub Pages HTTPS. It contains no backend credentials, upload endpoint, tracking, contact form, third-party JavaScript, or private database. Browser interactions operate locally on published aggregate evidence or synthetic records. The demo is suitable for public browsing; it does not expose the application backend.

To preview, run `python -m http.server 8080 --bind 127.0.0.1 --directory docs` and open `http://localhost:8080`. A local report is not an operational deployment of the underlying model or application.

## Release and rollback

1. Run the repository's quality checks and rebuild the demonstration from its documented input.
2. Review changes to data, claims and configuration; keep secrets and operational records outside version control.
3. Commit to the main branch. The Pages workflow publishes `docs/`; the quality workflow remains separate.
4. Check the live page, controls and downloaded evidence after publication.
5. Roll back by reverting the release commit and waiting for the deployment to succeed. No user-submitted records are stored by this site.

## Backend / operational adoption

The API is a single-host SQLite service with distinct reader/admin bearer roles, bounded requests/jobs, health/readiness endpoints and revisioned state. Configure distinct long random tokens through environment variables. Run one worker and keep SQLite state on persistent local storage. Never place credentials in the demo or repository.

The supplied container uses a non-root process and health probe. It is a deployment starting point, not evidence of a completed container/security certification. Operational adoption still requires TLS termination, managed identity appropriate to the organization, secret rotation, tested backups/restores, resource limits, monitoring and load/failure testing. Synthetic sensor results do not certify real-world policy compliance or sensor performance.
