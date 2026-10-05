from __future__ import annotations

from django.contrib import messages
from django.contrib.auth import login
from django.db import IntegrityError, transaction
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods

from .forms import PublicSignupForm


@require_http_methods(["GET", "POST"])
def signup_view(request):
    if request.user.is_authenticated:
        return redirect("organizations:workspace-selection")

    form = PublicSignupForm(
        request.POST or None,
    )

    if request.method == "POST" and form.is_valid():
        try:
            with transaction.atomic():
                user = form.save()
        except IntegrityError:
            form.add_error("email", "Unable to create this account. Try logging in.")
            return render(request, "registration/signup.html", {"form": form})

        login(
            request,
            user,
            backend="django.contrib.auth.backends.ModelBackend",
        )

        request.session["agentledger_new_account"] = True

        messages.success(
            request,
            "Your account is ready. Let's build your workspace.",
        )

        return redirect("billing:portfolio")

    return render(
        request,
        "registration/signup.html",
        {
            "form": form,
        },
    )
