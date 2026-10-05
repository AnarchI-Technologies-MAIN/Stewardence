"""Failure-only observations; do not retry claims or change queue predicates."""

from datetime import UTC, datetime

from django.db import connections


def claim_none_facts(job_id, *, using="default"):
    facts = {
        "scope": "post_claim_none_observation_not_claim_time",
        "python_clock": datetime.now(UTC).isoformat(),
        "skip_locked_row_lock_state": "not_observed",
    }
    try:
        with connections[using].cursor() as cursor:
            cursor.execute(
                """
                WITH observed AS MATERIALIZED (SELECT clock_timestamp() AS now)
                SELECT jsonb_build_object(
                 'database_clock',o.now,'session_role',session_user,
                 'isolation',current_setting('transaction_isolation'),
                 'job_exists',j.id IS NOT NULL,'status',j.status,
                 'job_type',j.job_type,'available_at',j.available_at,
                 'available',j.available_at<=o.now,
                 'available_lead_seconds',extract(epoch FROM j.available_at-o.now),
                 'queued',j.status='queued',
                 'core_work_allowed',app_private.core_work_allowed(j.organization_id),
                 'claim_eligibility_without_row_lock',j.status='queued'
                   AND j.available_at<=o.now AND (j.job_type<>'report_generation'
                     OR app_private.core_work_allowed(j.organization_id)),
                 'input_digest_valid',j.input_sha256 IS NOT DISTINCT FROM
                   encode(sha256(convert_to(
                     app_private.queue_canonical(j.payload),'UTF8')),'hex'),
                 'pause_present',EXISTS(SELECT 1 FROM core_health_controls h
                   WHERE h.organization_id=j.organization_id AND h.mode='paused'
                   AND NOT EXISTS(SELECT 1 FROM core_health_controls n
                     WHERE n.supersedes_id=h.id)),
                 'eligible_queue_count',(
                   SELECT count(*) FROM background_jobs q WHERE q.status='queued'
                   AND q.available_at<=o.now AND (q.job_type<>'report_generation'
                     OR app_private.core_work_allowed(q.organization_id))),
                 'subscriptions',coalesce((SELECT jsonb_agg(jsonb_build_object(
                   'status',s.status,'portfolio',s.portfolio,
                   'paid_access',app_private.paid_subscription_access(s.id),
                   'billing_user_is_owner',EXISTS(
                     SELECT 1 FROM organizations_organizationmember m
                     JOIN billing_billingcustomer b ON b.user_id=m.user_id
                     WHERE b.id=s.billing_customer_id
                       AND m.organization_id=s.organization_id AND m.role='owner'),
                   'coverage',coalesce((SELECT jsonb_agg(jsonb_build_object(
                     'start',p.service_start,'end',p.service_end,
                     'current',p.service_start<=o.now AND p.service_end>o.now))
                     FROM billing_paid_coverage p WHERE p.subscription_id=s.id),
                       '[]'::jsonb)))
                   FROM billing_subscription s
                   WHERE s.organization_id=j.organization_id),'[]'::jsonb))
                FROM observed o LEFT JOIN background_jobs j ON j.id=%s
                """,
                [job_id],
            )
            facts["database_observation"] = cursor.fetchone()[0]
    except Exception as diagnostic_error:
        facts["diagnostic_error_type"] = type(diagnostic_error).__name__
    return facts
