"""Click CLI entry point and subcommand routing."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

from kgmd.config import load_config, write_default_config
from kgmd.db import build_lock, get_connection, init_db
from kgmd.ingest import ingest_documents
from kgmd.query import (
    find_path,
    get_current_schema,
    get_entity,
    get_neighbors,
    list_entities,
    list_relations,
    search_chunks,
)

console = Console()
err_console = Console(stderr=True)


def find_corpus_dir(start: Path | None = None) -> Path:
    """Find the corpus directory by looking for .kgmd/ upward from start."""
    p = (start or Path.cwd()).resolve()
    while True:
        if (p / ".kgmd").is_dir():
            return p
        parent = p.parent
        if parent == p:
            break
        p = parent
    raise click.ClickException("No .kgmd directory found. Run 'kgmd init' first.")


def get_db_path(db: str | None, corpus_dir: Path | None = None) -> Path:
    """Resolve the database path from --db flag or corpus directory."""
    if db:
        return Path(db)
    cd = corpus_dir or find_corpus_dir()
    return cd / ".kgmd" / "graph.db"


@click.group()
@click.option("--debug", is_flag=True, help="Show full tracebacks on error.")
@click.pass_context
def main(ctx: click.Context, debug: bool) -> None:
    """kgmd — Knowledge graph from markdown files."""
    ctx.ensure_object(dict)
    ctx.obj["debug"] = debug
    if not debug:

        def handle_exception(exc_type, exc_value, exc_tb):
            if isinstance(exc_value, click.exceptions.Exit):
                sys.exit(exc_value.exit_code)
            if isinstance(exc_value, (click.ClickException, click.Abort)):
                raise exc_value
            err_console.print(f"[red]Error:[/red] {exc_value}")
            sys.exit(1)

        sys.excepthook = handle_exception


@main.command()
@click.option("--path", type=click.Path(), default=".", help="Directory to initialize.")
def init(path: str) -> None:
    """Initialize a new kgmd corpus."""
    corpus_dir = Path(path).resolve()
    kgmd_dir = corpus_dir / ".kgmd"

    if kgmd_dir.exists():
        console.print(f"Already initialized at [bold]{kgmd_dir}[/bold]")
        cfg_path = kgmd_dir / "config.yaml"
        if cfg_path.exists():
            console.print(cfg_path.read_text())
        return

    kgmd_dir.mkdir(parents=True)
    (kgmd_dir / "logs").mkdir()
    (kgmd_dir / "prompts").mkdir()

    # Write default config
    cfg_path = kgmd_dir / "config.yaml"
    write_default_config(cfg_path)

    # Initialize database
    db_path = kgmd_dir / "graph.db"
    conn = init_db(db_path)
    conn.close()

    console.print(f"[green]Initialized kgmd corpus at[/green] [bold]{corpus_dir}[/bold]")
    console.print(f"  Database: {db_path}")
    console.print(f"  Config:   {cfg_path}")


@main.command()
@click.option("--db", type=click.Path(), default=None, help="Path to graph.db")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
def stats(db: str | None, as_json: bool) -> None:
    """Show corpus statistics."""
    db_path = get_db_path(db)
    if not db_path.exists():
        raise click.ClickException(f"Database not found: {db_path}")

    conn = get_connection(db_path)
    try:
        doc_count = conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
        chunk_count = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
        entity_count = conn.execute("SELECT COUNT(*) FROM entities").fetchone()[0]
        relation_count = conn.execute("SELECT COUNT(*) FROM relations").fetchone()[0]

        # Entity counts by type
        type_rows = conn.execute(
            "SELECT entity_type, COUNT(*) as cnt FROM entities"
            " GROUP BY entity_type ORDER BY cnt DESC"
        ).fetchall()

        # Relation counts by predicate
        pred_rows = conn.execute(
            "SELECT predicate, COUNT(*) as cnt FROM relations GROUP BY predicate ORDER BY cnt DESC"
        ).fetchall()

        # Last extraction run
        last_extract = conn.execute(
            "SELECT * FROM extraction_runs ORDER BY id DESC LIMIT 1"
        ).fetchone()

        # Last resolution run
        last_resolve = conn.execute(
            "SELECT * FROM resolution_runs ORDER BY id DESC LIMIT 1"
        ).fetchone()
    finally:
        conn.close()

    if as_json:
        data = {
            "documents": doc_count,
            "chunks": chunk_count,
            "entities": entity_count,
            "relations": relation_count,
            "entity_types": {r["entity_type"]: r["cnt"] for r in type_rows},
            "relation_predicates": {r["predicate"]: r["cnt"] for r in pred_rows},
            "last_extraction": dict(last_extract) if last_extract else None,
            "last_resolution": dict(last_resolve) if last_resolve else None,
        }
        click.echo(json.dumps(data, indent=2))
        return

    console.print()
    table = Table(title="Corpus Statistics")
    table.add_column("Metric", style="bold")
    table.add_column("Value", justify="right")
    table.add_row("Documents", str(doc_count))
    table.add_row("Chunks", str(chunk_count))
    table.add_row("Entities", str(entity_count))
    table.add_row("Relations", str(relation_count))
    console.print(table)

    if type_rows:
        console.print()
        t = Table(title="Entities by Type")
        t.add_column("Type", style="cyan")
        t.add_column("Count", justify="right")
        for r in type_rows:
            t.add_row(r["entity_type"], str(r["cnt"]))
        console.print(t)

    if pred_rows:
        console.print()
        t = Table(title="Relations by Predicate")
        t.add_column("Predicate", style="cyan")
        t.add_column("Count", justify="right")
        for r in pred_rows:
            t.add_row(r["predicate"], str(r["cnt"]))
        console.print(t)

    if last_extract:
        console.print(
            f"\n[dim]Last extraction:[/dim] {last_extract['started_at']} — "
            f"status: {last_extract['status']}, docs: {last_extract['documents_processed']}"
        )
    if last_resolve:
        console.print(
            f"[dim]Last resolution:[/dim] {last_resolve['started_at']} — "
            f"status: {last_resolve['status']}, merges: {last_resolve['merges']}"
        )
    console.print()


@main.command()
@click.argument("path", default=".", type=click.Path(exists=True))
@click.option("--db", type=click.Path(), default=None, help="Path to graph.db")
@click.option("--config", "config_path", type=click.Path(), default=None, help="Config file path")
def build(path: str, db: str | None, config_path: str | None) -> None:
    """Build the knowledge graph: extract, resolve, induce."""
    corpus_dir = Path(path).resolve()
    kgmd_dir = corpus_dir / ".kgmd"
    if not kgmd_dir.exists():
        raise click.ClickException(
            f"Not a kgmd corpus (no .kgmd/ in {corpus_dir}). Run 'kgmd init' first."
        )

    config = load_config(corpus_dir)
    db_path = get_db_path(db, corpus_dir)
    conn = init_db(db_path)

    with build_lock(kgmd_dir):
        from kgmd.db import check_embedding_model
        from kgmd.embed import embed_new_chunks, embed_new_mentions, get_embedder
        from kgmd.extract import run_extraction
        from kgmd.induce import run_induction
        from kgmd.resolve import run_resolution

        # Stage 1: Ingest
        console.print("[bold]Stage 1: Ingesting documents...[/bold]")
        ing_stats = ingest_documents(conn, corpus_dir, config)
        console.print(
            f"  New: {ing_stats['new']}, Updated: {ing_stats['updated']}, "
            f"Skipped: {ing_stats['skipped']}, Chunks: {ing_stats['chunks_created']}"
        )

        # Stage 2: Embed chunks
        console.print("[bold]Stage 2: Embedding chunks...[/bold]")
        embedder = get_embedder(config)
        check_embedding_model(conn, embedder.model_id())
        n = embed_new_chunks(conn, embedder)
        console.print(f"  Embedded {n} new chunks")

        # Stage 3: Extract
        console.print("[bold]Stage 3: Extracting entities and relations...[/bold]")
        ext_stats = run_extraction(conn, corpus_dir, config)
        console.print(
            f"  Docs processed: {ext_stats['documents_processed']}, "
            f"Entities: {ext_stats['entities_created']}, "
            f"Relations: {ext_stats['relations_created']}"
        )

        # Stage 4: Embed mentions
        console.print("[bold]Stage 4: Embedding entity mentions...[/bold]")
        n = embed_new_mentions(conn, embedder)
        console.print(f"  Embedded {n} new mentions")

        # Stage 5: Resolve
        console.print("[bold]Stage 5: Resolving entities...[/bold]")
        res_stats = run_resolution(conn, config)
        console.print(f"  Merges: {res_stats['merges']}")

        # Stage 6: Induce
        console.print("[bold]Stage 6: Inducing schema...[/bold]")
        ind_stats = run_induction(conn, config)
        console.print(
            f"  Entity types: {ind_stats['entity_type_count']}, "
            f"Relation types: {ind_stats['relation_type_count']}"
        )

    conn.close()
    console.print("\n[green]Build complete.[/green]")


@main.command()
@click.argument("path", default=".", type=click.Path(exists=True))
@click.option("--db", type=click.Path(), default=None)
@click.option("--force", is_flag=True, help="Re-extract all documents, even unchanged ones.")
def extract(path: str, db: str | None, force: bool) -> None:
    """Extract entities and relations from documents."""
    corpus_dir = Path(path).resolve()
    kgmd_dir = corpus_dir / ".kgmd"
    if not kgmd_dir.exists():
        raise click.ClickException("Not a kgmd corpus. Run 'kgmd init' first.")

    config = load_config(corpus_dir)
    db_path = get_db_path(db, corpus_dir)
    conn = init_db(db_path)

    with build_lock(kgmd_dir):
        # Ingest first
        console.print("[bold]Ingesting documents...[/bold]")
        ing_stats = ingest_documents(conn, corpus_dir, config)
        console.print(
            f"  New: {ing_stats['new']}, Updated: {ing_stats['updated']}, "
            f"Skipped: {ing_stats['skipped']}"
        )

        # Embed chunks
        try:
            from kgmd.embed import embed_new_chunks, get_embedder

            embedder = get_embedder(config)
            from kgmd.db import check_embedding_model

            check_embedding_model(conn, embedder.model_id())
            embed_new_chunks(conn, embedder)
        except ImportError:
            pass

        # Extract
        from kgmd.extract import run_extraction

        console.print("[bold]Extracting...[/bold]")
        ext_stats = run_extraction(conn, corpus_dir, config, force=force)
        console.print(
            f"  Docs: {ext_stats['documents_processed']}, "
            f"Entities: {ext_stats['entities_created']}, "
            f"Relations: {ext_stats['relations_created']}"
        )

        # Embed mentions
        try:
            from kgmd.embed import embed_new_mentions

            embed_new_mentions(conn, embedder)
        except (ImportError, NameError):
            pass

    conn.close()
    console.print("[green]Extraction complete.[/green]")


@main.command()
@click.argument("path", default=".", type=click.Path(exists=True))
@click.option("--db", type=click.Path(), default=None)
def resolve(path: str, db: str | None) -> None:
    """Resolve duplicate entities."""
    corpus_dir = Path(path).resolve()
    kgmd_dir = corpus_dir / ".kgmd"
    if not kgmd_dir.exists():
        raise click.ClickException("Not a kgmd corpus. Run 'kgmd init' first.")

    config = load_config(corpus_dir)
    db_path = get_db_path(db, corpus_dir)
    conn = init_db(db_path)

    with build_lock(kgmd_dir):
        from kgmd.resolve import run_resolution

        console.print("[bold]Resolving entities...[/bold]")
        res_stats = run_resolution(conn, config, corpus_dir)
        console.print(f"  Merges: {res_stats['merges']}")

    conn.close()
    console.print("[green]Resolution complete.[/green]")


@main.command()
@click.argument("path", default=".", type=click.Path(exists=True))
@click.option("--db", type=click.Path(), default=None)
def induce(path: str, db: str | None) -> None:
    """Induce schema from the knowledge graph."""
    corpus_dir = Path(path).resolve()
    kgmd_dir = corpus_dir / ".kgmd"
    if not kgmd_dir.exists():
        raise click.ClickException("Not a kgmd corpus. Run 'kgmd init' first.")

    config = load_config(corpus_dir)
    db_path = get_db_path(db, corpus_dir)
    conn = init_db(db_path)

    with build_lock(kgmd_dir):
        from kgmd.induce import run_induction

        console.print("[bold]Inducing schema...[/bold]")
        ind_stats = run_induction(conn, config, corpus_dir)
        console.print(
            f"  Entity types: {ind_stats['entity_type_count']}, "
            f"Relation types: {ind_stats['relation_type_count']}"
        )

    conn.close()
    console.print("[green]Induction complete.[/green]")


@main.command()
@click.argument("query")
@click.option("--limit", "-n", default=10, help="Number of results.")
@click.option("--db", type=click.Path(), default=None)
@click.option("--json", "as_json", is_flag=True)
def find(query: str, limit: int, db: str | None, as_json: bool) -> None:
    """Semantic search over chunks."""
    corpus_dir = find_corpus_dir()
    config = load_config(corpus_dir)
    db_path = get_db_path(db, corpus_dir)
    conn = get_connection(db_path)

    from kgmd.embed import get_embedder

    embedder = get_embedder(config)
    query_vec = embedder.embed([query])[0]

    results = search_chunks(conn, query_vec, limit)
    conn.close()

    if as_json:
        click.echo(json.dumps(results, indent=2))
        return

    if not results:
        console.print("[dim]No results found.[/dim]")
        return

    for i, r in enumerate(results, 1):
        console.print(
            f"\n[bold]{i}.[/bold] [cyan]{r['document_path']}[/cyan] (distance: {r['distance']:.4f})"
        )
        text = r["chunk_text"][:300].replace("\n", " ")
        console.print(f"   {text}")
        if r["entities"]:
            names = ", ".join(f"{e['name']} ({e['type']})" for e in r["entities"])
            console.print(f"   [dim]Entities: {names}[/dim]")


@main.command("entities")
@click.option("--type", "entity_type", default=None, help="Filter by entity type.")
@click.option("--limit", "-n", default=50)
@click.option("--search", default=None, help="Substring search on name.")
@click.option("--db", type=click.Path(), default=None)
@click.option("--json", "as_json", is_flag=True)
def entities_cmd(
    entity_type: str | None, limit: int, search: str | None, db: str | None, as_json: bool
) -> None:
    """List entities."""
    db_path = get_db_path(db)
    conn = get_connection(db_path)
    results = list_entities(conn, entity_type=entity_type, search=search, limit=limit)
    conn.close()

    if as_json:
        click.echo(json.dumps(results, indent=2))
        return

    if not results:
        console.print("[dim]No entities found.[/dim]")
        return

    table = Table(title="Entities")
    table.add_column("Name", style="bold")
    table.add_column("Type", style="cyan")
    table.add_column("Attributes")
    for r in results:
        attrs = json.dumps(r["attributes"]) if r["attributes"] else ""
        table.add_row(r["name"], r["type"], attrs)
    console.print(table)


@main.command("relations")
@click.option("--predicate", default=None)
@click.option("--subject", default=None)
@click.option("--object", "object_name", default=None)
@click.option("--limit", "-n", default=50)
@click.option("--db", type=click.Path(), default=None)
@click.option("--json", "as_json", is_flag=True)
def relations_cmd(
    predicate: str | None,
    subject: str | None,
    object_name: str | None,
    limit: int,
    db: str | None,
    as_json: bool,
) -> None:
    """List relations."""
    db_path = get_db_path(db)
    conn = get_connection(db_path)
    results = list_relations(
        conn, predicate=predicate, subject=subject, object_name=object_name, limit=limit
    )
    conn.close()

    if as_json:
        click.echo(json.dumps(results, indent=2))
        return

    if not results:
        console.print("[dim]No relations found.[/dim]")
        return

    table = Table(title="Relations")
    table.add_column("Subject", style="bold")
    table.add_column("Predicate", style="green")
    table.add_column("Object", style="bold")
    table.add_column("Confidence", justify="right")
    for r in results:
        conf = f"{r['confidence']:.2f}" if r["confidence"] is not None else ""
        table.add_row(r["subject"], r["predicate"], r["object"], conf)
    console.print(table)


@main.command("entity")
@click.argument("name")
@click.option("--type", "entity_type", default=None)
@click.option("--db", type=click.Path(), default=None)
@click.option("--json", "as_json", is_flag=True)
def entity_cmd(name: str, entity_type: str | None, db: str | None, as_json: bool) -> None:
    """Show full record for a single entity."""
    db_path = get_db_path(db)
    conn = get_connection(db_path)
    result = get_entity(conn, name, entity_type)
    conn.close()

    if not result:
        raise click.ClickException(f"Entity '{name}' not found.")

    if as_json:
        click.echo(json.dumps(result, indent=2))
        return

    console.print(f"\n[bold]{result['name']}[/bold] [cyan]({result['type']})[/cyan]")
    if result["attributes"]:
        console.print(f"  Attributes: {json.dumps(result['attributes'])}")

    if result["mentions"]:
        console.print(f"\n  [dim]Mentions ({len(result['mentions'])}):[/dim]")
        for m in result["mentions"][:10]:
            console.print(f'    - "{m["surface_form"]}" in {m["document"]}')

    if result["outgoing_relations"]:
        console.print("\n  [dim]Outgoing relations:[/dim]")
        for r in result["outgoing_relations"]:
            console.print(f"    → {r['predicate']} → {r['object']} ({r['object_type']})")

    if result["incoming_relations"]:
        console.print("\n  [dim]Incoming relations:[/dim]")
        for r in result["incoming_relations"]:
            console.print(f"    ← {r['predicate']} ← {r['subject']} ({r['subject_type']})")
    console.print()


@main.command("neighbors")
@click.argument("name")
@click.option("--depth", "-d", default=1, help="Traversal depth.")
@click.option("--type", "entity_type", default=None)
@click.option("--db", type=click.Path(), default=None)
@click.option("--json", "as_json", is_flag=True)
def neighbors_cmd(
    name: str, depth: int, entity_type: str | None, db: str | None, as_json: bool
) -> None:
    """Subgraph traversal around an entity."""
    db_path = get_db_path(db)
    conn = get_connection(db_path)
    result = get_neighbors(conn, name, depth, entity_type)
    conn.close()

    if as_json:
        click.echo(json.dumps(result, indent=2))
        return

    if not result["nodes"]:
        console.print(f"[dim]Entity '{name}' not found or has no neighbors.[/dim]")
        return

    console.print(f"\n[bold]Neighbors of {name} (depth={depth}):[/bold]")
    console.print(f"\n  Nodes ({len(result['nodes'])}):")
    for n in result["nodes"]:
        console.print(f"    - {n['name']} ({n['type']})")
    console.print(f"\n  Edges ({len(result['edges'])}):")
    for e in result["edges"]:
        console.print(f"    {e['source']} → {e['predicate']} → {e['target']}")
    console.print()


@main.command("path")
@click.argument("from_name")
@click.argument("to_name")
@click.option("--max-depth", default=5)
@click.option("--db", type=click.Path(), default=None)
@click.option("--json", "as_json", is_flag=True)
def path_cmd(from_name: str, to_name: str, max_depth: int, db: str | None, as_json: bool) -> None:
    """Find shortest path between two entities."""
    db_path = get_db_path(db)
    conn = get_connection(db_path)
    result = find_path(conn, from_name, to_name, max_depth)
    conn.close()

    if as_json:
        click.echo(json.dumps(result, indent=2))
        return

    if result is None:
        console.print(f"[dim]No path found between '{from_name}' and '{to_name}'.[/dim]")
        return

    console.print(f"\n[bold]Path: {from_name} → {to_name}[/bold]")
    for e in result:
        console.print(f"  {e['source']} → [green]{e['predicate']}[/green] → {e['target']}")
    console.print()


@main.command("schema")
@click.option("--db", type=click.Path(), default=None)
@click.option("--json", "as_json", is_flag=True)
def schema_cmd(db: str | None, as_json: bool) -> None:
    """Show the current induced schema."""
    import yaml

    db_path = get_db_path(db)
    conn = get_connection(db_path)
    result = get_current_schema(conn)
    conn.close()

    if not result:
        console.print(
            "[dim]No schema has been induced yet. Run 'kgmd build' or 'kgmd induce'.[/dim]"
        )
        return

    if as_json:
        click.echo(json.dumps(result, indent=2))
        return

    console.print(f"\n[bold]Schema v{result['id']}[/bold] ({result['created_at']})")
    console.print(f"  Model: {result['llm_model']}")
    console.print(f"  Entity types: {result['entity_type_count']}")
    console.print(f"  Relation types: {result['relation_type_count']}")
    console.print()
    console.print(yaml.dump(result["schema"], default_flow_style=False))


@main.command("export")
@click.option("--format", "fmt", type=click.Choice(["jsonld", "cypher", "graphml"]), required=True)
@click.option(
    "--output", "-o", type=click.Path(), default=None, help="Output file path. Stdout if omitted."
)
@click.option("--db", type=click.Path(), default=None)
def export_cmd(fmt: str, output: str | None, db: str | None) -> None:
    """Export the knowledge graph."""
    from kgmd.export import export_cypher, export_graphml, export_jsonld

    db_path = get_db_path(db)
    conn = get_connection(db_path)

    if fmt == "jsonld":
        content = export_jsonld(conn)
    elif fmt == "cypher":
        content = export_cypher(conn)
    elif fmt == "graphml":
        content = export_graphml(conn)
    else:
        raise click.ClickException(f"Unknown format: {fmt}")

    conn.close()

    if output:
        Path(output).write_text(content)
        console.print(f"[green]Exported to {output}[/green]")
    else:
        click.echo(content)


@main.command()
@click.option("--hard", is_flag=True, help="Also remove documents and chunks.")
@click.confirmation_option(prompt="This will delete all graph data. Continue?")
def reset(hard: bool) -> None:
    """Reset the knowledge graph, keeping config and prompts.

    By default, keeps documents and chunks so re-extraction can skip unchanged files.
    Use --hard to wipe everything and start completely fresh.
    """
    corpus_dir = find_corpus_dir()
    kgmd_dir = corpus_dir / ".kgmd"
    db_path = kgmd_dir / "graph.db"

    if not db_path.exists():
        raise click.ClickException(f"Database not found: {db_path}")

    conn = get_connection(db_path)

    with build_lock(kgmd_dir):
        # Always clear graph data
        conn.execute("DELETE FROM relations")
        conn.execute("DELETE FROM entity_mentions")
        conn.execute("DELETE FROM entities")
        conn.execute("DELETE FROM schema_versions")
        conn.execute("DELETE FROM resolution_runs")
        conn.execute("DELETE FROM extraction_runs")
        # Reset extraction state so docs get reprocessed
        conn.execute("UPDATE documents SET last_extracted_hash = NULL")

        if hard:
            conn.execute("DELETE FROM chunks")
            conn.execute("DELETE FROM documents")

        conn.execute("VACUUM")
        conn.commit()

    conn.close()

    # Clear build log
    log_path = kgmd_dir / "logs" / "build.log"
    if log_path.exists():
        log_path.write_text("")

    if hard:
        console.print("[green]Full reset complete.[/green] All data cleared.")
    else:
        console.print(
            "[green]Reset complete.[/green] Graph data cleared, documents/chunks preserved.\n"
            "Run [bold]kgmd build[/bold] to re-extract."
        )


@main.command("mcp")
def mcp_cmd() -> None:
    """Launch MCP server over stdio."""
    from kgmd.mcp_server import run_server

    run_server()
