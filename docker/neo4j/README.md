# Local Neo4j for OpenForge

This compose file runs self-hosted Neo4j Community Edition only. Neo4j Aura
and other cloud-hosted variants are intentionally out of scope.

Start it from the repository root:

```bash
docker compose -f docker/neo4j/docker-compose.yml up -d
```

Defaults:

- Bolt URI: `bolt://localhost:7687`
- Browser: `http://localhost:7474`
- Username: `neo4j`
- Password: `openforge`

Override local defaults with environment variables such as
`OPENFORGE_NEO4J_USER`, `OPENFORGE_NEO4J_PASSWORD`,
`OPENFORGE_NEO4J_BOLT_PORT`, and `OPENFORGE_NEO4J_HTTP_PORT`.
