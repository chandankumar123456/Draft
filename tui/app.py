from textual.app import App
from textual.widgets import Static

class DraftApp(App):
    """Draft Terminal UI."""
    
    def compose(self):
        yield Static("Draft")
        
        
if __name__ == "__main__":
    DraftApp().run()