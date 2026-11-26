"""Generate real SQL policy probes from explicit, synthetic table fixtures."""
from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4


TABLES = (
    "cases", "sessions", "generated_notes", "counseling_drafts", "case_memory_chunks",
    "evidence_items", "verification_reports", "retrieval_logs", "document_exports",
    "transcript_turns", "transcript_windows", "voucher_documents",
)
PRIVATE_TABLES = ("voucher_recovery.deletions", "voucher_recovery.source_context", "beta_retention.enrollments")
PUBLIC_TABLES = (*TABLES, "kb_documents", "kb_chunks", "client_links", "client_check_ins")
# Client check-ins are written by the client account, not by the counselor who owns the case, so
# they cannot use the A/B counselor fixture above. They are covered by their own probes.
CLIENT_TABLES = ("client_links", "client_check_ins")
PARENT_TABLES = tuple(table for table in TABLES if table not in {
    "cases", "counseling_drafts", "document_exports", "retrieval_logs",
})
VECTOR = "array_fill(0.125::real, array[1536])::extensions.vector"


class SQL(str):
    """A fixed SQL expression authored below, never caller input."""


def quote(value):
    if isinstance(value, SQL):
        return str(value)
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, dict):
        return quote(json.dumps(value, separators=(",", ":"))) + "::jsonb"
    return "'" + str(value).replace("'", "''") + "'"


def fixture():
    owner = str(uuid4())
    ids = {name: str(uuid4()) for name in TABLES}
    ids["cases"] = "poc_synthetic_" + str(uuid4())
    common = {"user_id": owner, "case_id": ids["cases"]}
    linked = {**common, "session_id": ids["sessions"]}
    rows = {
        "cases": {"id": ids["cases"], "user_id": owner, "counselor_id": owner, "case_alias": "Synthetic case"},
        "sessions": {"id": ids["sessions"], **common, "session_number": 1, "sanitized_input_text": "Synthetic source"},
        "generated_notes": {"id": ids["generated_notes"], **linked, "confirmation_status": "confirmed",
            "draft_json": {"session_content": {"text": "Synthetic draft"}}, "confirmed_json": {"sections": {"session_content": "Synthetic confirmed"}}},
        "counseling_drafts": {"draft_id": ids["counseling_drafts"], **common, "session_number": 1, "data": {"synthetic": True}},
        "case_memory_chunks": {"id": ids["case_memory_chunks"], **linked, "counselor_id": owner,
            "source_note_id": ids["generated_notes"], "field_type": "session_content", "chunk_text": "Synthetic memory",
            "source_ref": "confirmed_note:" + ids["generated_notes"] + ":session_content", "embedding": SQL(VECTOR)},
        "evidence_items": {"id": ids["evidence_items"], **linked, "source_text": "Synthetic evidence"},
        "verification_reports": {"id": ids["verification_reports"], **linked,
            "note_id": ids["generated_notes"], "report_json": {"synthetic": True}},
        "retrieval_logs": {"id": ids["retrieval_logs"], **common, "counselor_id": owner,
            "retrieval_scope": "case_memory", "query_hash": "synthetic-hash"},
        "document_exports": {"id": ids["document_exports"], **common, "title": "Synthetic export"},
        "transcript_turns": {"id": ids["transcript_turns"], **linked, "counselor_id": owner,
            "turn_index": 0, "speaker_role": "client", "sanitized_text": "Synthetic turn"},
        "transcript_windows": {"id": ids["transcript_windows"], **linked, "counselor_id": owner,
            "start_turn_index": 0, "end_turn_index": 0, "window_text": "Synthetic window",
            "source_ref": "transcript:" + ids["sessions"] + ":0-0", "content_hash": "synthetic-hash", "embedding": SQL(VECTOR)},
        "voucher_documents": {"id": ids["voucher_documents"], **common, "operation_key": str(uuid4()),
            "request_hash": "synthetic-hash", "template": "form10", "fingerprint": "synthetic-fingerprint", "privacy_status": "applied",
            "snapshot": {"form": {"edition": "ari-2026"}, "sources": {ids["generated_notes"]: "synthetic-hash"}}},
    }
    return owner, ids, rows


def insert(table, row):
    return f"insert into public.{table} ({','.join(row)}) values ({','.join(quote(value) for value in row.values())})"


def key(table):
    return "draft_id" if table == "counseling_drafts" else "id"


def probe_row(table, row):
    """Avoid unrelated unique constraints hiding a missing ownership check."""
    changed = {**row, key(table): str(uuid4())}
    if table == "sessions":
        changed["session_number"] = 991
    if table == "case_memory_chunks":
        changed["field_type"] = "synthetic_probe"
    if table == "transcript_turns":
        changed["turn_index"] = 991
    if table == "transcript_windows":
        changed.update(start_turn_index=991, end_turn_index=991, source_ref="synthetic_probe:" + str(uuid4()))
    if table == "voucher_documents":
        changed["operation_key"] = str(uuid4())
    return changed


def build_sql() -> str:
    lines = ["begin;", Path(__file__).with_name("assertions.sql").read_text(encoding="utf-8")]
    a, b = fixture(), fixture()

    def actor(owner=None, role="authenticated"):
        lines.extend(["reset role;", f"set local role {role};",
            f"set local request.jwt.claim.sub = {quote(owner or '')};",
            f"set local request.jwt.claim.role = {quote(role)};"])

    def admin():
        lines.append("reset role;")

    def count(statement, expected, label):
        lines.append(f"select poc_test.count_is({quote(statement)}, {expected}, {quote(label)});")

    def changed(statement, expected, label):
        count(f"with affected as ({statement} returning 1) select count(*) from affected", expected, label)

    def denied(statement, label, codes=("42501",)):
        lines.append(f"select poc_test.denied({quote(statement)}, {quote(label)}, array[{','.join(map(quote, codes))}]);")

    def truth(statement, label):
        lines.append(f"select poc_test.truth({quote(statement)}, {quote(label)});")

    def succeeds(statement, label):
        lines.append(f"select poc_test.succeeds({quote(statement)}, {quote(label)});")

    lines.append(f"insert into auth.users(id) values ({quote(a[0])}),({quote(b[0])});")
    # All counseling inserts execute as the owning role; setup cannot mask broken positive policies.
    for label, (owner, ids, rows) in (("A", a), ("B", b)):
        actor(owner)
        truth("select not rolsuper and not rolbypassrls from pg_roles where rolname=current_user", label + ":real_rls_role")
        for table in TABLES:
            truth(f"select row_security_active('public.{table}')", label + ":" + table + ":rls_active")
            changed(insert(table, rows[table]), 1, label + ":" + table + ":own_insert")

    # Client check-ins: a client account writes, reads and deletes only its own entries, and the
    # counselor who owns the case reads them with no write policy of its own. Neither party may
    # update or delete a link row directly; the cross-party transitions run in SECURITY DEFINER
    # functions. Accepting an invite writes platform app metadata that the synthetic identity
    # table does not model, so the post-acceptance link state is prepared as an administrator
    # here; the definer path itself is exercised by backend/test_client_check_ins.py.
    client, other_client = str(uuid4()), str(uuid4())
    admin()
    lines.append(f"insert into auth.users(id) values ({quote(client)}),({quote(other_client)});")
    link_id = str(uuid4())
    invite = {"id": link_id, "case_id": a[1]["cases"], "user_id": a[0], "status": "invited",
              "invite_token_hash": SQL(quote("1" * 64)), "invite_expires_at": SQL("now() + interval '7 days'")}
    actor(a[0])
    changed(insert("client_links", invite), 1, "A:client_links:own_invite")
    count("select count(*) from public.client_links", 1, "A:client_links:only_own_visible")
    denied("update public.client_links set status='ended' where id=" + quote(link_id),
           "A:client_links:no_direct_update")
    denied("delete from public.client_links where id=" + quote(link_id),
           "A:client_links:no_direct_delete")
    denied(insert("client_links", {**invite, "id": str(uuid4()), "case_id": b[1]["cases"]}),
           "A:client_links:foreign_case_invite")
    actor(b[0])
    count(f"select count(*) from public.client_links where id={quote(link_id)}", 0, "B:client_links:foreign_select")
    actor(client)
    count("select count(*) from public.client_links", 0, "client:client_links:hidden_before_accept")
    denied(insert("client_links", {**invite, "id": str(uuid4()), "user_id": client}),
           "client:client_links:no_counselor_invite")
    admin()
    lines.append(f"update public.client_links set status='active', client_user_id={quote(client)}, "
                 "invite_token_hash=null, consent_version='synthetic-v1', consented_at=now(), accepted_at=now() "
                 f"where id={quote(link_id)};")
    actor(client)
    count("select count(*) from public.client_links", 1, "client:client_links:own_after_accept")
    check_in = {"id": str(uuid4()), "link_id": link_id, "mood": 7, "note": "Synthetic check-in"}
    changed(insert("client_check_ins", check_in), 1, "client:client_check_ins:own_insert")
    count("select count(*) from public.client_check_ins", 1, "client:client_check_ins:only_own_visible")
    denied("update public.client_check_ins set note='edited' where id=" + quote(check_in["id"]),
           "client:client_check_ins:no_direct_update")
    denied(insert("client_check_ins", {**check_in, "id": str(uuid4()), "client_user_id": other_client}),
           "client:client_check_ins:spoofed_client")
    denied(insert("client_check_ins", {**check_in, "id": str(uuid4()), "mood": 11}),
           "client:client_check_ins:mood_range", ("23514",))
    actor()
    for table in CLIENT_TABLES:
        count(f"select count(*) from public.{table}", 0, "missing_subject:" + table)
    actor(a[0])
    count("select count(*) from public.client_check_ins", 1, "A:client_check_ins:read_own_case")
    denied(insert("client_check_ins", {**check_in, "id": str(uuid4())}), "A:client_check_ins:no_insert")
    denied("update public.client_check_ins set note='edited' where id=" + quote(check_in["id"]),
           "A:client_check_ins:no_update")
    actor(b[0])
    count("select count(*) from public.client_check_ins", 0, "B:client_check_ins:foreign_select")
    denied(f"select public.end_client_link({quote(link_id)})", "B:client_links:foreign_end", ("P0002",))
    actor(other_client)
    count("select count(*) from public.client_check_ins", 0, "foreign_client:client_check_ins:hidden")
    denied(insert("client_check_ins", {**check_in, "id": str(uuid4())}),
           "foreign_client:client_check_ins:foreign_link")
    actor(client)
    succeeds(f"select public.end_client_link({quote(link_id)})", "client:client_links:client_end")
    denied(insert("client_check_ins", {**check_in, "id": str(uuid4())}),
           "client:client_check_ins:ended_link_blocks")
    count("select count(*) from public.client_check_ins", 1, "client:client_check_ins:history_kept")
    actor(a[0])
    count("select count(*) from public.client_check_ins", 1, "A:client_check_ins:history_kept_after_end")
    actor(client)
    changed("delete from public.client_check_ins where id=" + quote(check_in["id"]), 1,
            "client:client_check_ins:own_delete")

    for label, own, other in (("A", a, b), ("B", b, a)):
        actor(own[0])
        for table in TABLES:
            ident, other_ident = quote(own[1][table]), quote(other[1][table])
            prefix = label + ":" + table + ":"
            count(f"select count(*) from public.{table}", 1, prefix + "only_own_visible")
            count(f"select count(*) from public.{table} where {key(table)}={other_ident}", 0, prefix + "foreign_select")
            changed(f"update public.{table} set user_id=user_id where {key(table)}={other_ident}", 0, prefix + "foreign_update")
            changed(f"delete from public.{table} where {key(table)}={other_ident}", 0, prefix + "foreign_delete")
            update = {
                "cases": "case_alias='Synthetic edited case'", "sessions": "session_title='Synthetic edited session'",
                "generated_notes": "counselor_edited=true", "counseling_drafts": "data='{\"synthetic_edit\":true}'::jsonb",
                "case_memory_chunks": "chunk_text='Synthetic edited memory'", "evidence_items": "source_text='Synthetic edited evidence'",
                "verification_reports": "report_json='{\"synthetic_edit\":true}'::jsonb", "retrieval_logs": "query_length=2",
                "document_exports": "title='Synthetic edited export'", "transcript_turns": "sanitized_text='Synthetic edited turn'",
                "transcript_windows": "window_text='Synthetic edited window'",
                "voucher_documents": f"reviewed_at=now(),reviewed_by={quote(own[0])}",
            }[table]
            changed(f"update public.{table} set {update} where {key(table)}={ident}", 1, prefix + "own_update")
            denied(f"update public.{table} set user_id={quote(other[0])} where {key(table)}={ident}",
                prefix + "owner_transfer", ("42501", "23514", "P0001"))
            row = probe_row(table, own[2][table])
            row["user_id"] = other[0]
            denied(insert(table, row), prefix + "foreign_owner_insert", ("42501", "23514", "P0001"))

            if table in PARENT_TABLES:
                # These should be rejected even when an attacker owns the child row.
                row = probe_row(table, own[2][table])
                row["case_id"] = other[1]["cases"]
                denied(insert(table, row), prefix + "forged_case_insert", ("42501", "23503", "23514", "P0001"))
                extra = ",session_number=992" if table == "sessions" else ""
                denied(f"update public.{table} set case_id={quote(other[1]['cases'])}{extra} where {key(table)}={ident}",
                    prefix + "forged_case_update", ("42501", "23503", "23514", "P0001"))

            parents = {"session_id": "sessions", "note_id": "generated_notes", "source_note_id": "generated_notes"}
            for column, parent in parents.items():
                if column not in own[2][table] and not (table == "generated_notes" and column == "source_note_id"):
                    continue
                row = probe_row(table, own[2][table])
                row[column] = other[1][parent]
                denied(insert(table, row), prefix + "forged_" + column + "_insert", ("42501", "23503", "23514", "P0001"))
                denied(f"update public.{table} set {column}={quote(other[1][parent])} where {key(table)}={ident}",
                    prefix + "forged_" + column + "_update", ("42501", "23503", "23514", "P0001"))

        # These tables deliberately support unsaved case IDs; do not invent a parent requirement.
        for table in ("counseling_drafts", "document_exports", "retrieval_logs"):
            row = probe_row(table, own[2][table])
            row["case_id"] = "poc_unsaved_" + str(uuid4())
            changed(insert(table, row), 1, label + ":" + table + ":unsaved_case_insert")
            changed(f"delete from public.{table} where {key(table)}={quote(row[key(table)])}", 1,
                    label + ":" + table + ":unsaved_case_cleanup")

        voucher = probe_row("voucher_documents", own[2]["voucher_documents"])
        voucher["snapshot"] = {"form": {"edition": "ari-2026"}, "sources": {other[1]["generated_notes"]: "synthetic-forgery"}}
        denied(insert("voucher_documents", voucher), label + ":voucher:forged_source", ("42501", "P0001"))
        for column, value in (("detached_source_ids", SQL("array['" + str(uuid4()) + "'::uuid]")), ("restored_from", str(uuid4()))):
            voucher = probe_row("voucher_documents", own[2]["voucher_documents"])
            voucher[column] = value
            denied(insert("voucher_documents", voucher), label + ":voucher:forged_" + column)

        for rpc, args in (
            ("match_case_memory_chunks", f"{VECTOR},{quote(own[0])},{quote(own[1]['cases'])},null,5"),
            ("match_transcript_windows", f"{VECTOR},{quote(own[0])},{quote(own[1]['cases'])},12"),
        ):
            count(f"select count(*) from public.{rpc}({args})", 1, label + ":" + rpc + ":own")
            foreign = args.replace(quote(own[0]), quote(other[0])).replace(quote(own[1]["cases"]), quote(other[1]["cases"]))
            count(f"select count(*) from public.{rpc}({foreign})", 0, label + ":" + rpc + ":spoof_owner")
            cross_case = args.replace(quote(own[1]["cases"]), quote(other[1]["cases"]))
            count(f"select count(*) from public.{rpc}({cross_case})", 0, label + ":" + rpc + ":foreign_case")

    # Anonymous access remains denied even if a caller supplies a subject claim.
    for suffix, owner in (("empty", None), ("spoofed_subject", a[0])):
        actor(owner, "anon")
        for table in PUBLIC_TABLES:
            denied(f"select * from public.{table}", "anon:" + suffix + ":" + table)
        for table in PRIVATE_TABLES:
            denied(f"select * from {table}", "anon:" + suffix + ":" + table)
        for rpc in (f"match_case_memory_chunks({VECTOR},{quote(a[0])},{quote(a[1]['cases'])})",
                    f"match_transcript_windows({VECTOR},{quote(a[0])},{quote(a[1]['cases'])})",
                    f"match_kb_chunks({VECTOR})", "hybrid_search_kb('synthetic')",
                    f"voucher_deletion_history({quote(a[1]['cases'])})", f"restore_deleted_voucher({quote(str(uuid4()))})"):
            denied("select * from public." + rpc, "anon:" + suffix + ":rpc:" + rpc.split("(")[0])

    actor()
    for table in TABLES:
        count(f"select count(*) from public.{table}", 0, "missing_subject:" + table)
    denied(insert("cases", probe_row("cases", a[2]["cases"])), "missing_subject:insert")

    # Shared reference knowledge is readable, not writable, and never contains counseling fixtures.
    admin()
    document, chunk = str(uuid4()), str(uuid4())
    lines.append(insert("kb_documents", {"id": document, "title": "Synthetic reference", "doc_category": "document_template"}) + ";")
    lines.append(insert("kb_chunks", {"id": chunk, "document_id": document, "chunk_text": "synthetic reference",
        "embedding": SQL(VECTOR)}) + ";")
    for label, own in (("A", a), ("B", b)):
        actor(own[0])
        for table in ("kb_documents", "kb_chunks"):
            count(f"select count(*) from public.{table}", 1, label + ":" + table + ":shared_read")
            denied(f"delete from public.{table}", label + ":" + table + ":no_delete")
            denied(f"update public.{table} set id=id", label + ":" + table + ":no_update")
        denied(insert("kb_documents", {"title": "Forbidden synthetic", "doc_category": "document_template"}), label + ":kb:no_insert")
        count(f"select count(*) from public.match_kb_chunks({VECTOR})", 1, label + ":kb:dense")
        count("select count(*) from public.hybrid_search_kb('synthetic')", 1, label + ":kb:hybrid")

    # Archive real owned deletions, then exercise both definer-backed RPC entry points.
    events = {}
    for label, own in (("A", a), ("B", b)):
        actor(own[0])
        changed(f"delete from public.voucher_documents where id={quote(own[1]['voucher_documents'])}", 1, label + ":voucher:archive")
        admin()
        events[label] = str(uuid4())
        lines.append(f"update voucher_recovery.deletions set event_id={quote(events[label])} where document_id={quote(own[1]['voucher_documents'])};")
    for label, own, foreign_label, other in (("A", a, "B", b), ("B", b, "A", a)):
        actor(own[0])
        count(f"select jsonb_array_length(public.voucher_deletion_history({quote(own[1]['cases'])}))", 1, label + ":recovery:own_history")
        count(f"select jsonb_array_length(public.voucher_deletion_history({quote(other[1]['cases'])}))", 0, label + ":recovery:foreign_history")
        truth(f"select public.restore_deleted_voucher({quote(events[foreign_label])})->>'status'='missing'", label + ":recovery:foreign_restore")
        truth(f"select public.restore_deleted_voucher({quote(events[label])})->>'status'='ok'", label + ":recovery:own_restore")
        truth(f"select public.restore_deleted_voucher({quote(events[label])})->>'status'='ok'", label + ":recovery:idempotent_restore")
        for table in PRIVATE_TABLES:
            denied(f"select * from {table}", label + ":private_table:" + table)
        for signature in ("public.guard_voucher_snapshot()", "public.delete_note_voucher_documents()",
                          "public.reject_generated_note_id_change()", "voucher_recovery.capture_deletion()",
                          "voucher_recovery.purge_expired()", "beta_retention.check_write()",
                          "beta_retention.enroll(uuid,uuid,timestamp with time zone)",
                          "beta_retention.withdraw(uuid,uuid)", "beta_retention.erase_due(uuid)"):
            schema, name = signature.split("(")[0].split(".")
            truth("select count(*)>0 and not bool_or(has_function_privilege(current_user,p.oid,'execute')) "
                  "from pg_proc p join pg_namespace n on n.oid=p.pronamespace "
                  f"where n.nspname={quote(schema)} and p.proname={quote(name)}", label + ":private_function:" + signature)

    # Positive DELETE for both owners, in foreign-key order, and verify the other user is unaffected.
    for label, own, other in (("A", a, b), ("B", b, a)):
        actor(own[0])
        for table in reversed(TABLES):
            changed(f"delete from public.{table} where {key(table)}={quote(own[1][table])}", 1, label + ":" + table + ":own_delete")
        if label == "A":
            actor(other[0])
            for table in TABLES:
                count(f"select count(*) from public.{table}", 1, "B:" + table + ":survives_A_delete")
    admin()
    for table in PRIVATE_TABLES[:2]:
        count(f"select count(*) from {table}", 0, "case_delete:cleanup:" + table)
    # Inventory is deliberate: adding a counseling table must add a fixture, not silently escape coverage.
    expected = "array[" + ",".join(quote(name) for name in sorted(PUBLIC_TABLES)) + "]::text[]"
    truth("select array_agg(tablename::text order by tablename)=" + expected +
          " from pg_tables where schemaname='public'", "inventory:all_public_tables")
    truth("select count(*)=2 from cron.job where jobname in ('voucher-deletion-retention','remind-beta-retention')",
          "scheduler:both_source_migration_jobs_registered")
    lines.extend(["select json_build_object('label',label,'passed',passed,'diagnostic',diagnostic)::text from poc_test.results order by label;", "rollback;"])
    return "\n".join(lines) + "\n"
