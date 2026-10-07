BEGIN;

-- Running upgrade qr01 -> rd01

INSERT INTO stack_tags (id, title, kind, direction_id, sort_order) VALUES ('kotlin', 'Kotlin', 'language', 'backend', 90);

INSERT INTO stack_tags (id, title, kind, direction_id, sort_order) VALUES ('csharp', 'C#', 'language', 'backend', 90);

INSERT INTO stack_tags (id, title, kind, direction_id, sort_order) VALUES ('php', 'PHP', 'language', 'backend', 90);

INSERT INTO stack_tags (id, title, kind, direction_id, sort_order) VALUES ('kubernetes', 'Kubernetes', 'tool', NULL, 90);

UPDATE alembic_version SET version_num='rd01' WHERE alembic_version.version_num = 'qr01';

COMMIT;

