# Database Manual

## Connection Snapshot
- Source: `postgresql://neondb_owner:npg_rLGPUg2JMko4@ep-damp-unit-akcpcdbt-pooler.c-3.us-west-2.aws.neon.tech/neondb?sslmode=require&channel_binding=require`
- `chunks.embedding` dimension: 1536

## Table Summary
| Table | Rows | Columns |
| --- | --- | --- |
| `answer_feedback` | 1 | 11 |
| `chat_messages` | 142 | 7 |
| `chat_sessions` | 38 | 6 |
| `chunks` | 8254 | 10 |
| `documents` | 2217 | 6 |
| `repo_files` | 84 | 10 |
| `repo_onboarding_jobs` | 5 | 11 |

## `answer_feedback`
Rows: 1

| Column | Type | Nullable | Default |
| --- | --- | --- | --- |
| `id` | `bigint` | `false` | `nextval('answer_feedback_id_seq'::regclass)` |
| `session_id` | `character varying(64)` | `true` | `` |
| `collection` | `character varying(128)` | `false` | `'default'::character varying` |
| `mode` | `character varying(64)` | `false` | `'default'::character varying` |
| `verdict` | `character varying(16)` | `false` | `` |
| `question` | `text` | `true` | `` |
| `answer` | `text` | `true` | `` |
| `comment` | `text` | `true` | `` |
| `citations` | `jsonb` | `true` | `'[]'::jsonb` |
| `metadata` | `jsonb` | `true` | `'{}'::jsonb` |
| `created_at` | `timestamp with time zone` | `false` | `now()` |

Indexes:
- `answer_feedback_pkey`: `CREATE UNIQUE INDEX answer_feedback_pkey ON public.answer_feedback USING btree (id)`
- `idx_answer_feedback_collection_created`: `CREATE INDEX idx_answer_feedback_collection_created ON public.answer_feedback USING btree (collection, created_at DESC)`

## `chat_messages`
Rows: 142

| Column | Type | Nullable | Default |
| --- | --- | --- | --- |
| `id` | `bigint` | `false` | `nextval('chat_messages_id_seq'::regclass)` |
| `session_id` | `character varying(64)` | `false` | `` |
| `role` | `character varying(16)` | `false` | `` |
| `content` | `text` | `false` | `` |
| `citations` | `jsonb` | `true` | `'[]'::jsonb` |
| `metadata` | `jsonb` | `true` | `'{}'::jsonb` |
| `created_at` | `timestamp with time zone` | `false` | `now()` |

Indexes:
- `chat_messages_pkey`: `CREATE UNIQUE INDEX chat_messages_pkey ON public.chat_messages USING btree (id)`
- `idx_chat_messages_session_id`: `CREATE INDEX idx_chat_messages_session_id ON public.chat_messages USING btree (session_id, id)`

## `chat_sessions`
Rows: 38

| Column | Type | Nullable | Default |
| --- | --- | --- | --- |
| `session_id` | `character varying(64)` | `false` | `` |
| `collection` | `character varying(128)` | `false` | `'default'::character varying` |
| `mode` | `character varying(64)` | `false` | `'default'::character varying` |
| `metadata` | `jsonb` | `true` | `'{}'::jsonb` |
| `created_at` | `timestamp with time zone` | `false` | `now()` |
| `updated_at` | `timestamp with time zone` | `false` | `now()` |

Indexes:
- `chat_sessions_pkey`: `CREATE UNIQUE INDEX chat_sessions_pkey ON public.chat_sessions USING btree (session_id)`

## `chunks`
Rows: 8254

| Column | Type | Nullable | Default |
| --- | --- | --- | --- |
| `id` | `bigint` | `false` | `nextval('chunks_id_seq'::regclass)` |
| `document_id` | `bigint` | `false` | `` |
| `chunk_index` | `integer` | `false` | `` |
| `content` | `text` | `false` | `` |
| `embedding` | `vector(1536)` | `true` | `` |
| `token_count` | `integer` | `true` | `` |
| `source_file` | `text` | `true` | `` |
| `line_start` | `integer` | `true` | `` |
| `line_end` | `integer` | `true` | `` |
| `created_at` | `timestamp with time zone` | `false` | `now()` |

Indexes:
- `chunks_pkey`: `CREATE UNIQUE INDEX chunks_pkey ON public.chunks USING btree (id)`
- `idx_chunks_document_id`: `CREATE INDEX idx_chunks_document_id ON public.chunks USING btree (document_id)`
- `idx_chunks_embedding`: `CREATE INDEX idx_chunks_embedding ON public.chunks USING ivfflat (embedding vector_cosine_ops) WITH (lists='100')`

## `documents`
Rows: 2217

| Column | Type | Nullable | Default |
| --- | --- | --- | --- |
| `id` | `bigint` | `false` | `nextval('documents_id_seq'::regclass)` |
| `s3_key` | `text` | `false` | `` |
| `sha256` | `character varying(64)` | `false` | `` |
| `collection` | `character varying(128)` | `false` | `'default'::character varying` |
| `created_at` | `timestamp with time zone` | `false` | `now()` |
| `metadata` | `jsonb` | `true` | `'{}'::jsonb` |

Indexes:
- `documents_pkey`: `CREATE UNIQUE INDEX documents_pkey ON public.documents USING btree (id)`
- `idx_documents_collection`: `CREATE INDEX idx_documents_collection ON public.documents USING btree (collection)`
- `idx_documents_sha256`: `CREATE UNIQUE INDEX idx_documents_sha256 ON public.documents USING btree (sha256, collection)`

## `repo_files`
Rows: 84

| Column | Type | Nullable | Default |
| --- | --- | --- | --- |
| `id` | `bigint` | `false` | `nextval('repo_files_id_seq'::regclass)` |
| `collection` | `character varying(128)` | `false` | `` |
| `owner` | `character varying(128)` | `false` | `` |
| `repo` | `character varying(128)` | `false` | `` |
| `ref` | `character varying(128)` | `false` | `'main'::character varying` |
| `file_path` | `text` | `false` | `` |
| `file_sha` | `character varying(64)` | `true` | `` |
| `file_size` | `integer` | `true` | `0` |
| `embedded` | `boolean` | `false` | `false` |
| `created_at` | `timestamp with time zone` | `false` | `now()` |

Indexes:
- `idx_repo_files_collection`: `CREATE INDEX idx_repo_files_collection ON public.repo_files USING btree (collection)`
- `idx_repo_files_embedded`: `CREATE INDEX idx_repo_files_embedded ON public.repo_files USING btree (collection, embedded)`
- `repo_files_pkey`: `CREATE UNIQUE INDEX repo_files_pkey ON public.repo_files USING btree (id)`
- `repo_files_unique`: `CREATE UNIQUE INDEX repo_files_unique ON public.repo_files USING btree (collection, file_path)`

## `repo_onboarding_jobs`
Rows: 5

| Column | Type | Nullable | Default |
| --- | --- | --- | --- |
| `job_id` | `character varying(64)` | `false` | `` |
| `collection` | `character varying(128)` | `false` | `'default'::character varying` |
| `principal` | `character varying(128)` | `false` | `'unknown'::character varying` |
| `status` | `character varying(16)` | `false` | `'queued'::character varying` |
| `request_payload` | `jsonb` | `false` | `'{}'::jsonb` |
| `result` | `jsonb` | `true` | `'{}'::jsonb` |
| `error` | `text` | `true` | `` |
| `created_at` | `timestamp with time zone` | `false` | `now()` |
| `updated_at` | `timestamp with time zone` | `false` | `now()` |
| `started_at` | `timestamp with time zone` | `true` | `` |
| `finished_at` | `timestamp with time zone` | `true` | `` |

Indexes:
- `idx_repo_onboarding_jobs_collection_created`: `CREATE INDEX idx_repo_onboarding_jobs_collection_created ON public.repo_onboarding_jobs USING btree (collection, created_at DESC)`
- `repo_onboarding_jobs_pkey`: `CREATE UNIQUE INDEX repo_onboarding_jobs_pkey ON public.repo_onboarding_jobs USING btree (job_id)`

