# Export Reference
> Applies to kgmd 0.2.x

For anyone moving a built graph into another tool: this page describes the three formats
`kgmd export` can emit, exactly what each one contains, and which downstream tool consumes it. After
reading it you can pick a format, write it to a file, and know what will and will not survive the
trip.

## Usage

```bash
kgmd export --format FORMAT [--output FILE] [--db PATH]
```

`--format` is required and accepts `jsonld`, `cypher`, or `graphml`. Without `--output` the document
is written to stdout, so it pipes; with `--output` (or `-o`) it is written to that path and the
command prints a one-line confirmation instead. `--db` selects an alternate database file; by
default the corpus database is used. Full flag details are in the [CLI reference](./cli.md).

All three formats are built from the same query: every row of the entities table and every row of
the relations table. Nothing else is exported — documents, chunks, entity mentions, the induced
schema, and embeddings all stay in the database. Export is read-only and takes no build lock, so it
is safe to run against a corpus at any time.

One shared caveat: relation endpoints are re-resolved by canonical name while the document is
written. If two entities share a canonical name, every edge touching that name is attributed to the
first of them, and a name that resolves to nothing becomes entity id `0`.

## Formats

### jsonld

A single JSON object with two members. `@context` binds the `schema` prefix to schema.org, binds the
`kg` prefix to a kgmd-local namespace, and maps the bare terms `name` and `type` onto `schema:name`
and `@type`. `@graph` holds every entity node followed by every relation edge.

An entity node carries `@id` in the form `kg:entity/<id>`, its canonical `name`, a `type` mapped to
a schema.org class where kgmd recognizes the entity type (Person, Organization, Location, Place,
Event, Project, Technology, and Product; Technology maps to `schema:SoftwareApplication`, while any
unrecognized type becomes `kg:<Type>`), and `kg:entityType` with the unmapped type string. Each
entity attribute is emitted as its own `kg:<attribute>` member.

A relation edge is an object typed `kg:Relation` with `kg:subject` and `kg:object` holding node
references, `kg:predicate` holding the raw predicate string, `kg:confidence` when a confidence was
recorded, and one `kg:<attribute>` member per relation attribute.

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
      "name": "Brian Anderson",
      "type": "schema:Person",
      "kg:entityType": "Person",
      "kg:role": "CTO"
    },
    {
      "@type": "kg:Relation",
      "kg:subject": "kg:entity/1",
      "kg:predicate": "works_for",
      "kg:object": "kg:entity/2",
      "kg:confidence": 0.95
    }
  ]
}
```

Consume it with generic linked-data tooling: any JSON-LD processor, an RDF triple store after
expansion, or plain JSON tools such as `jq` when you only need the graph as data.

```bash
kgmd export --format jsonld --output graph.jsonld
```

### cypher

A newline-separated script of `CREATE` statements, nodes first, then relationships. Each entity
becomes `CREATE (e<id>:<Label> {name: '...'});`, where the label is the entity type with spaces
replaced by underscores and the property map holds the canonical name plus every entity attribute.
Each relation becomes `CREATE (e<subject>)-[:<PREDICATE>]->(e<object>);`, where the relationship
type is the predicate uppercased with spaces replaced by underscores, and the property map — omitted
entirely when there is nothing to write — holds the relation attributes plus `confidence`.

Property keys have spaces and hyphens replaced by underscores. String values are single-quoted with
backslashes and single quotes escaped; numbers are written bare.

```text
CREATE (e1:Person {name: 'Brian Anderson', role: 'CTO'});
CREATE (e2:Organization {name: 'Acme Corp'});
CREATE (e1)-[:WORKS_FOR {confidence: 0.95}]->(e2);
```

Consume it with Neo4j, by feeding the script to `cypher-shell` or pasting it into Neo4j Browser. The
script is plain `CREATE`, with no constraints, indexes, `MERGE`, or transaction wrapper, so running
it twice against the same database produces a second copy of the graph. Load it into an empty
database, or clear the previous import first.

```bash
kgmd export --format cypher --output graph.cypher
```

### graphml

Standard GraphML for a directed graph, produced through NetworkX. Node ids are entity ids rendered
as strings. Every node carries `label` (the canonical name) and `entity_type`, plus one key per
entity attribute. Every edge carries `label` and `predicate` — both the predicate string — and
`confidence`, which is the empty string when no confidence was recorded. All values are written as
GraphML string attributes, including numeric confidences.

```text
<graphml xmlns="http://graphml.graphdrawing.org/xmlns">
  <key id="d1" for="node" attr.name="entity_type" attr.type="string" />
  <key id="d0" for="node" attr.name="label" attr.type="string" />
  <graph edgedefault="directed">
    <node id="1">
      <data key="d0">Brian Anderson</data>
      <data key="d1">Person</data>
    </node>
    <edge source="1" target="2">
      <data key="d3">works_for</data>
    </edge>
  </graph>
</graphml>
```

Consume it with Gephi or yEd for visual layout and inspection, or read it back into NetworkX for
programmatic analysis. Because the export is built on a simple directed graph, at most one edge is
kept per ordered pair of entities: when two relations share the same subject and object, the last
one written overwrites the first, and only its predicate and confidence survive. Use `jsonld` or
`cypher` when multiple relations between the same two entities matter.

```bash
kgmd export --format graphml --output graph.graphml
```

## Choosing a format

| Format | Keeps parallel edges | Keeps typed values | Best for |
|---|---|---|---|
| `jsonld` | yes | yes | data interchange, RDF pipelines, scripted post-processing |
| `cypher` | yes | yes | loading into Neo4j for property-graph queries |
| `graphml` | no | no, everything is stringified | visual exploration in Gephi or yEd, analysis in NetworkX |

For a worked end-to-end run that builds a graph and exports it, see the
[graph export walkthrough](../examples/graph-export.md).
