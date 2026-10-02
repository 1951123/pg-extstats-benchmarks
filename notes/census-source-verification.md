# Census source accessibility verification

Verification timestamp: `2026-10-02T01:41:42Z`

All downloads were made only into the temporary directory
`/tmp/pgextbench-census-source-check.Y4RoUg`. No downloaded file was copied
into `benchmarks/`, and no PostgreSQL connection or database operation was
performed.

## Dataset

- Requested URL: `https://archive.ics.uci.edu/static/public/116/us+census+data+1990.zip`
- Effective URL: unchanged
- HTTP status: `200`
- Declared content type: not provided by the server (`Content-Type` absent)
- Downloaded bytes: `168626076`
- SHA256: `a9a1b84168456ab65b0f2fba7df2c1025aac15b61cd9667c6459f83dcf30b61a`
- Archive format: ZIP
- ZIP integrity: passed (`testzip` returned no corrupt member)
- Archive entries: `15`
- Total uncompressed bytes: `1224496185`
- Download status: accessible and verified in temporary storage only

## Workload

- Source page: `https://github.com/wuziniu/BayesCard/blob/master/Benchmark/Census/query.sql`
- Retrieved raw URL: `https://raw.githubusercontent.com/wuziniu/BayesCard/master/Benchmark/Census/query.sql`
- Effective URL: unchanged raw URL
- HTTP status: `200`
- Content type: `text/plain; charset=utf-8`
- Downloaded bytes: `93884`
- SHA256: `e581c088a4e4281c79cbdc5ea8502ba657eb2efd7d656d6ab7973eba05d8f861`
- Line count: `468` newline-terminated lines (`468` logical lines)
- Download status: accessible and verified in temporary storage only

No Census adapter, manifest, loader, PostgreSQL database, experiment, or
benchmark artifact was created or modified by this verification.
