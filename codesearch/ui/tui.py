from pathlib import Path

import lancedb
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Header, Footer, Input, SelectionList, Label, Static, Markdown
from textual.widgets.selection_list import Selection

from codesearch.embedding.embedder import SentenceTransformersEmbedder

class SearchResultWidget(Static):
    def __init__(self, item: dict, **kwargs):
        super().__init__(**kwargs)
        self.item = item
        
    def compose(self) -> ComposeResult:
        file_path = self.item.get("file_path", "unknown")
        lines = f"{self.item.get('start_line', '?')}-{self.item.get('end_line', '?')}"
        score = self.item.get("_relevance_score", self.item.get("_score", self.item.get("_distance", 0)))
        
        yield Label(f"[bold cyan]{file_path}[/] (Lines: {lines}) | Score: {score:.3f}")
        yield Markdown(f"```python\n{self.item.get('text', '')}\n```")


class CodeSearchTUI(App):
    CSS = """
    #left-pane {
        width: 30%;
        dock: left;
        border-right: solid green;
    }
    #right-pane {
        width: 70%;
        padding: 1;
    }
    SearchResultWidget {
        padding: 1;
        margin: 1;
        border: solid green;
    }
    Input {
        dock: top;
        margin-bottom: 1;
    }
    #results-container {
        height: 100%;
        overflow-y: auto;
    }
    """
    
    def __init__(self):
        super().__init__()
        self.db_base = Path("~/.lancedb").expanduser()
        self.embedder = SentenceTransformersEmbedder("sentence-transformers/all-MiniLM-L6-v2")
        
    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        
        with Horizontal():
            with Vertical(id="left-pane"):
                yield Label("Select Repositories to Search:", classes="header-label")
                yield SelectionList(id="repo-list")
                
            with Vertical(id="right-pane"):
                yield Input(placeholder="Enter search query (e.g. 'def main')...", id="search-input")
                with VerticalScroll(id="results-container"):
                    yield Label("Press Enter in the search bar above to begin.", id="placeholder-msg")
                    
        yield Footer()

    def on_mount(self) -> None:
        # Load repositories
        repo_list = self.query_one("#repo-list", SelectionList)
        if self.db_base.exists():
            for d in self.db_base.iterdir():
                if d.is_dir() and (d / "chunks.lance").exists():
                    repo_list.add_option(Selection(d.name, d.name, initial_state=True))
                    
    async def on_input_submitted(self, message: Input.Submitted) -> None:
        query = message.value
        if not query.strip():
            return
            
        selected_repos = self.query_one("#repo-list", SelectionList).selected
        if not selected_repos:
            self.notify("Please select at least one repository from the left panel.", title="Error", severity="error")
            return
            
        container = self.query_one("#results-container", VerticalScroll)
        await container.query("*").remove()
        
        self.notify(f"Searching {len(selected_repos)} repo(s)...")
        # Ensure we wait briefly so the UI updates
        await container.mount(Label(f"Loading results for '{query}'..."))
        
        try:
            # We do embedding synchronously. Since it's quick, this is acceptable for a local TUI prototype.
            query_vec = self.embedder.embed_texts([query])[0]
            
            await container.query("*").remove()
            
            for repo_name in selected_repos:
                db_path = self.db_base / repo_name
                db = lancedb.connect(str(db_path))
                tbl = db.open_table("chunks")
                
                # Hybrid Search
                results = tbl.search(query_type="hybrid").vector(query_vec).text(query).limit(5).to_list()
                
                await container.mount(Label(f"\n[bold yellow]Results from '{repo_name}':[/bold yellow]"))
                for row in results:
                    await container.mount(SearchResultWidget(row))
        except Exception as e:
            await container.query("*").remove()
            await container.mount(Label(f"[bold red]Search error:[/] {e}"))
            self.notify(f"Search failed", severity="error")


def main():
    app = CodeSearchTUI()
    app.run()

if __name__ == "__main__":
    main()
