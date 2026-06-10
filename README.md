# Inspect AI tutorial

...

# FAQ

<details>
<summary>How to share notebooks with Inspect widgets (evals() output)?</summary>

When you commit a Jupyter Notebook containing `inspect_ai` progress widgets to GitHub, the interactive components do not display. Instead, some sites, including GitHub, only render a static `Output()` text placeholder.

## Option 1: Use Jupyter NBViewer (easiest way)

[Jupyter NBViewer](https://nbviewer.org) reads the saved widget state directly from your `.ipynb` file's content and renders it visually as a static webpage.

1. Enable automatic widget state saving in your Jupyter:
    * **JupyterLab**: Go to **Settings** -> Check **Save Widget State Automatically**.
    * **Classic Notebook**: Go to **Widgets** -> Click **Save Notebook Widget State**.
2. Run your cells so the widgets appear on your screen, then save the notebook.
3. Commit and push your `.ipynb` file to your GitHub repository.
4. Copy your GitHub notebook URL and paste it into the [Jupyter NBViewer](https://nbviewer.org).

## Option 2: Export Notebook to HTML

You can convert your notebook (with saved widgets) into a standalone HTML file to share it on your site.

```bash
jupyter nbconvert --to html your_notebook.ipynb
```
</details>

<details>
<summary>Why some cells are slow?</summary>    

It takes some time (especially when using local models, e.g. with Ollama) to run the `eval()` function. So don't rerun these cells if it is not necessary. Also, you can use fewer examples via the `eval(limit=1)` param to test your setup.
</details>

<details>
<summary>My task was interrupted. What should I do?</summary>

If your run was interrupted, you can continue it if you have defined the task as follows and saved the interim logfile.

```python
from inspect_ai import Task, task, eval, eval_retry

@task
def final_task():
    return Task(
            dataset=...
    )
...

result = eval(...)  # it creates log file when it starts

...

log = eval_retry("logs/your_log_name.eval")[0]
```

</details>

<details>
<summary>other question?</summary>

...
</details>
