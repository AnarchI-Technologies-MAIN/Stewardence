STEWARDENCE COLLECTOR 0.1.0

1. Extract the entire release archive to a new folder.
2. Open PowerShell in that folder.
3. Run: .\Stewardence-Collector.ps1
4. Review the generated JSON evidence bundle.
5. Sign in to Stewardence and upload the JSON from Collector evidence.

The bootstrapper verifies the signed installation profile, executable SHA-256,
and module-manifest SHA-256 before it runs the Collector. It stores a
pseudonymous device UUID in the current Windows user's Local AppData folder so
later one-shot scans can be compared without collecting a person or device name.

MVP scope is limited to installed-program name, version, publisher and registry
location from standard Windows uninstall registry keys. Installation alone does
not prove use, paid subscription, granted permissions, data access, or product
capabilities. The Collector does not run continuously, install a service, read
documents, collect secrets, or make changes to installed software.

The release profile is cryptographically signed, but the executable does not
carry an Authenticode publisher certificate. Windows may therefore show an
unknown-publisher warning. Confirm the release SHA-256 on the Stewardence
Download page before proceeding.
