# Railway configuration boundary

The accepted topology is `web`, `worker`, and `renderer` plus private PostgreSQL and a private reports bucket.

The original requested `railway/*.toml` files are not created because Railway's current official documentation says new services cannot opt into the deprecated Config-as-Code mechanism. Executable Railway Infrastructure as Code will be generated and verified with the current Railway CLI as `.railway/railway.ts` during the bounded deployment milestone. This documentation file prevents an empty directory from falsely implying that executable Railway configuration already exists.
