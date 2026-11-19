# Disposable SQL verification only; never used by an application deployment.
FROM postgres:15.20-bookworm@sha256:8180c3e1b9b603d2988f937dfbe51008bad5c4b07c77f35119695c027a7315ab

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential ca-certificates git postgresql-server-dev-15 \
    && git clone --depth 1 --branch v0.8.1 https://github.com/pgvector/pgvector.git /tmp/pgvector \
    && test "$(git -C /tmp/pgvector rev-parse HEAD)" = "778dacf20c07caf904557a88705142631818d8cb" \
    && make -C /tmp/pgvector OPTFLAGS="" \
    && make -C /tmp/pgvector install \
    && git clone --depth 1 --branch v1.6.7 https://github.com/citusdata/pg_cron.git /tmp/pg_cron \
    && test "$(git -C /tmp/pg_cron rev-parse HEAD)" = "465b38c737f584d520229f5a1d69d1d44649e4e5" \
    && make -C /tmp/pg_cron \
    && make -C /tmp/pg_cron install \
    && rm -rf /tmp/pgvector /tmp/pg_cron /var/lib/apt/lists/*
