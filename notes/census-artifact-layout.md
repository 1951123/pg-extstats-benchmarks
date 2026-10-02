# Census artifact layout

Inspection date: 2026-10-02

No `census-prepared-v1` directory was present under an external
`PGEXTADV_BENCHMARK_DATA` root. The previously verified source archive at
`/tmp/pgextbench-census-source-check.Y4RoUg/census.zip` was inspected without
copying it into the repository or extracting it into benchmark artifacts.

The archive is a ZIP containing 15 files. The primary prepared source for this
pipeline is `USCensus1990.data.txt`:

- encoding: UTF-8-compatible ASCII bytes
- delimiter: comma
- line ending: CRLF
- header: present
- columns: 69, with unique names
- uncompressed size: 361,344,227 bytes
- compressed size: 54,435,916 bytes
- rows including header: 2,458,286
- data rows: 2,458,285
- maximum observed line length: 592 bytes

The other data file, `USCensus1990raw.data.txt`, is preserved by preparation
but is not loaded by this phase. It is tab-delimited, has no header, contains
125 fields per row, and is 862,858,036 bytes uncompressed (2,458,286 rows).

The archive also contains documentation, attribute descriptions, an HTML
coding file, and `USCensus1990.mapping.sql`. No workload SQL is executed by
the loader.

The generated schema maps source header names to PostgreSQL lowercase column
names so the workload's unquoted identifiers retain their intended meaning;
the prepared manifest records both source `columns` and `database_columns`.
