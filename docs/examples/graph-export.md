# Walkthrough: Load the Graph Into Another Tool
> Applies to kgmd 0.2.x

For anyone who wants the graph outside kgmd — laid out visually in Gephi or yEd, queried with Cypher
in Neo4j, or consumed as linked data. By the end you will have exported the same graph in two
formats, will know exactly which node and edge properties travel with it, and will know what the
export leaves behind.

## Goal

Serialize `.kgmd/graph.db` into GraphML and Cypher with `kgmd export`, load each into its target
tool, and understand the mapping: entities become nodes, relations become directed edges, and
nothing else in the database is exported.

## Prerequisites

- kgmd 0.2.0 installed, and a corpus already built with `kgmd build` so that entities and relations
  exist. `kgmd stats` shows non-zero counts for both. Exporting an empty graph is not an error — it
  produces a well-formed but nodeless document (and, for `cypher`, an empty file).
- The external tool you intend to load into: Gephi or yEd for GraphML, Neo4j (`cypher-shell` or the
  Neo4j Browser) for Cypher. Nothing kgmd-specific needs installing on that side.
- **No git checkout is required.** Exporting works from the installed wheel against your own corpus.
  A checkout is only needed if you want to reproduce this page against the seven sample notes under
  `tests/fixtures/`, which are test fixtures and are not shipped in the published wheel.

## Corpus

Use any built corpus. For a reproducible export, build the graph from the seven fixture notes in a
git checkout — `tests/fixtures/acme_corp.md`, `tests/fixtures/brian_anderson.md`,
`tests/fixtures/digital_transformation.md`, `tests/fixtures/partnerships.md`,
`tests/fixtures/quarterly_review.md`, `tests/fixtures/sarah_chen.md`, and
`tests/fixtures/tech_stack.md` — which yields a graph of people, organizations, and projects that is
large enough to lay out and small enough to read. Your own notes, built as in
[personal-notes.md](./personal-notes.md), work identically.

## Steps

### 1. Export the two files

```bash
cd ~/notes
kgmd export --format graphml -o graph.graphml
kgmd export --format cypher -o graph.cypher
```

Each command prints `Exported to <path>` on success. Omit `--output` / `-o` and the serialization
goes to stdout instead, which is what you want when piping:

```bash
kgmd export --format jsonld | jq '.["@graph"] | length'
```

Like the other read commands, `kgmd export` finds `.kgmd/graph.db` by walking up from the working
directory, or takes an explicit `--db` path. All three formats read the same two tables — entities
and relations — so the three files describe exactly the same graph.

### 2. Open the GraphML in Gephi or yEd

GraphML is the format to use for layout and visual exploration. Open `graph.graphml` directly
(Gephi: **File > Open**; yEd: **File > Open**). The file declares `edgedefault="directed"`, one
`<key>` per node or edge property, and one `<data>` element per value:

- Node `id` is the kgmd entity row id, as a string.
- Node `label` is the canonical entity name, `entity_type` is the entity's type, and each entity
  attribute becomes a further node key named after the attribute. Every key is declared
  `attr.type="string"`, so numeric attributes arrive as strings.
- Edge `label` and `predicate` both carry the relation predicate; `confidence` carries the
  extraction confidence as a string, empty when the relation has none.

In Gephi, `entity_type` is the attribute to partition on for colour, and `label` is the display
label. In yEd, a hierarchic or organic layout over the same file is usually enough to see the
clusters.

### 3. Load the Cypher into Neo4j

`graph.cypher` is a flat list of `CREATE` statements: first one statement per entity, then one per
relation. Node statements bind a variable `e<id>` matching the entity row id; relation statements
refer to those variables:

```bash
cypher-shell -u neo4j -p "$NEO4J_PASSWORD" --file graph.cypher
```

Cypher variables are scoped to the statement that binds them. Because the relation statements
reference variables bound by earlier node statements, the file has to be evaluated with those
bindings still in scope. If your loader splits the file on `;` and runs each statement
independently, the relation statements will not resolve `e1` and will silently create fresh empty
nodes instead of connecting the existing ones — check the node count after loading, and prefer
GraphML or JSON-LD if your loader works that way.

The entity type becomes the node label (spaces replaced by underscores) and the predicate becomes
the relationship type, upper-cased with spaces replaced by underscores. Property values are
single-quoted with backslashes and single quotes escaped.

### 4. Or take JSON-LD for linked-data tooling

```bash
kgmd export --format jsonld -o graph.jsonld
```

`jsonld` is the format for RDF stores, SPARQL front ends, and anything that consumes `@context`
documents. Known entity types are mapped onto schema.org — `Person`, `Organization`,
`Location`/`Place`, `Event`, `Project`, `Product`, and `Technology` (which maps to
`schema:SoftwareApplication`) — and everything else falls back to the `kg:` prefix. The original
kgmd type is always preserved in `kg:entityType`, so no information is lost in the mapping.

Note the shape before you write queries against it: relations are **reified** as their own objects
in `@graph` with `@type` of `kg:Relation` and `kg:subject` / `kg:object` pointing at node `@id`s.
They are not direct properties linking one node to another, so a naive triple query over the
document will not traverse them.

## Expected output

`kgmd export --format graphml`, truncated to two nodes and one edge:

```text
<?xml version='1.0' encoding='utf-8'?>
<graphml xmlns="http://graphml.graphdrawing.org/xmlns" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:schemaLocation="http://graphml.graphdrawing.org/xmlns http://graphml.graphdrawing.org/xmlns/1.0/graphml.xsd">
  <key id="d5" for="edge" attr.name="confidence" attr.type="string" />
  <key id="d4" for="edge" attr.name="predicate" attr.type="string" />
  <key id="d3" for="edge" attr.name="label" attr.type="string" />
  <key id="d2" for="node" attr.name="role" attr.type="string" />
  <key id="d1" for="node" attr.name="entity_type" attr.type="string" />
  <key id="d0" for="node" attr.name="label" attr.type="string" />
  <graph edgedefault="directed">
    <node id="1">
      <data key="d0">Sarah Chen</data>
      <data key="d1">Person</data>
      <data key="d2">Software Engineer</data>
    </node>
    <node id="2">
      <data key="d0">Acme Corp</data>
      <data key="d1">Organization</data>
    </node>
    <edge source="1" target="2">
      <data key="d3">works_at</data>
      <data key="d4">works_at</data>
      <data key="d5">0.95</data>
    </edge>
  </graph>
</graphml>
```

`kgmd export --format cypher`, truncated to three nodes and two relations — one statement per line,
each terminated with a semicolon:

```text
CREATE (e1:Person {name: 'Sarah Chen', role: 'Software Engineer'});
CREATE (e2:Organization {name: 'Acme Corp'});
CREATE (e3:Project {name: 'Digital Transformation'});
CREATE (e1)-[:WORKS_AT {confidence: 0.95}]->(e2);
CREATE (e1)-[:DESIGNED {confidence: 0.9}]->(e3);
```

`kgmd export --format jsonld`, truncated to one node and one relation:

```json
{
  "@context": {
    "schema": "https://schema.org/",
    "kg": "https://kgmd.local/",
    "name": "schema:name",
    "type": "@type"
  },
  "@graph": [
    {
      "@id": "kg:entity/1",
      "name": "Sarah Chen",
      "type": "schema:Person",
      "kg:entityType": "Person",
      "kg:role": "Software Engineer"
    },
    {
      "@type": "kg:Relation",
      "kg:subject": "kg:entity/1",
      "kg:predicate": "works_at",
      "kg:object": "kg:entity/2",
      "kg:confidence": 0.95
    }
  ]
}
```

In every format the node count equals the `Entities` row of `kgmd stats` and the edge count equals
the `Relations` row, with the one GraphML exception noted below. Field-by-field details are in
[export.md](../reference/export.md).

## Limitations

- **An export is a snapshot, not a live sync.** Nothing connects the exported file back to
  `.kgmd/graph.db`. Re-export after every `kgmd build`, and re-import on the other side; edits made
  in Gephi or Neo4j never flow back into kgmd.
- **Node ids are not stable across rebuilds.** Ids are database row ids. Resolution deletes merged
  entities, and `kgmd reset` clears and vacuums the tables, so the same entity can carry a different
  id after the next build. Do not use them as durable keys — join on the canonical name instead.
- **GraphML collapses parallel relations.** The GraphML writer builds a directed graph keyed by
  ordered node pair, so if two relations share the same subject and object, only the last one
  written survives in that file. Cypher and JSON-LD keep every relation, so check there if an edge
  count looks short.
- **Only entities and relations are exported.** Documents, chunks, mention surface forms, the
  evidence chunk that justified each relation, extraction and resolution run history, and the
  embedding vectors all stay in `.kgmd/graph.db`. An exported node cannot be traced back to the
  sentence it came from — use `kgmd entity` or the MCP server for that.
- **The induced schema is a separate artifact.** It is not part of any export. Read it with
  `kgmd schema`, which prints the schema version, the model that induced it, the type counts, and
  the schema body as YAML, or `kgmd schema --json` for the same record as JSON. Carry it across by
  hand if the target tool wants a type definition.
- **Cypher property values are formatted, not parameterized.** Strings are escaped and inlined, so
  entity names containing unusual characters should be spot-checked after loading; and because
  relation statements depend on earlier variable bindings, the file is not safe to split into
  independent statements.
