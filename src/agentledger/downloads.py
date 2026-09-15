
from django.shortcuts import render

COLLECTOR_RELEASE = {
    "version": "0.2.0",
    "asset_name": "StewardSensors-setup.exe",
    "asset_url": (
        "https://github.com/AnarchI-Technologies-MAIN/"
        "stewardence-mvp-v1.8/releases/download/stewardsensors-v0.2.0/"
        "StewardSensors-setup.exe"
    ),
    # Replaced with the exact release metadata values when v0.2.0 is built.
    "sha256": "67ac4b3220d1ddd6864df193cd2495d2b448583d663df42c3f4425a44618a8a5",
    "executable_sha256": "660771f8a0f8e28705cea589fead6ffd5694bab56f3eb62e5c9f3cabf3a3ea13",
    "profile_sha256": "5e974fbc70836a4faa540d462e5f2a61a246e4f7afd3ad9792436a717d2d644c",
    "public_key_sha256": (
        "c6208fe13ee170ca940752100c053625b82c6b63bdad1f3a660ff7e7e841ae4f"
    ),
    "available_module": "Windows Installed Programs",
}

POST_MVP_MODULES = (
    "Microsoft 365 Intelligence",
    "Google Workspace Intelligence",
    "GitHub Intelligence",
    "Accounting Intelligence",
    "Browser Intelligence",
    "Developer Tooling Intelligence",
    "Continuous Observation",
    "Desktop Portal",
)


def download_view(request):
    return render(
        request,
        "downloads/detail.html",
        {
            "release": COLLECTOR_RELEASE,
            "post_mvp_modules": POST_MVP_MODULES,
        },
    )
