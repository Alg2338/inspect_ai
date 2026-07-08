# Inspect AI tutorial

<a href="https://discord.gg/GPnm8GSCy"><img src="https://img.shields.io/badge/discord-Join_us-blue?logo=Discord"></a>
<a href="mailto:alexgorb2002@gmail.com"><img src="https://img.shields.io/badge/gmail-Email_us-D14836?logo=gmail"></a>

This repository contains Jupyter Notebook tutorial for Inspect AI.

[Inspect AI](https://inspect.aisi.org.uk/) is a widely used library for AI evaluations.

This tutorial covers real-world use cases and essential theory. Every part has its (slightly different) Google Colab version in the `colab` branch. You can also ask NotebookLM about tutorials <a href="https://notebooklm.google.com/notebook/4f27e99a-0262-4aef-bb00-85e3bbec331a"><img src="https://img.shields.io/badge/NotebookLM-open-4285F4?logo=notebookLM"></a>.

Each tutorial comes with assignments for practice.

## How to start

You can clone the repository

```
git clone https://github.com/Alg2338/inspect_ai.git
```

and open the first notebook.

Or open the Google Colab version (see links below).

## Content

| # | Tutorial | Description | Google Colab |
|---|---|---|---|
| 1 | [inspect_ai_tutorial_1_basics.ipynb](inspect_ai_tutorial_1_basics.ipynb)         | Learn the basics of Inspect AI and create your first evaluation. | <a href="https://colab.research.google.com/github/Alg2338/inspect_ai/blob/colab/inspect_ai_tutorial_1_basics.ipynb"><img src="https://colab.research.google.com/assets/colab-badge.svg" width = '' ></a>     |
| 2 | [inspect_ai_tutorial_2_statistics.ipynb](inspect_ai_tutorial_2_statistics.ipynb) | Work with the statistical elements of evaluations.               | <a href="https://colab.research.google.com/github/Alg2338/inspect_ai/blob/colab/inspect_ai_tutorial_2_statistics.ipynb"><img src="https://colab.research.google.com/assets/colab-badge.svg" width = '' ></a> | 
| 3 | [inspect_ai_tutorial_3_llm_judge.ipynb](inspect_ai_tutorial_3_llm_judge.ipynb)   | Learn how to evaluate using the LLM-as-a-Judge approach.         | <a href="https://colab.research.google.com/github/Alg2338/inspect_ai/blob/colab/inspect_ai_tutorial_3_llm_judge.ipynb"><img src="https://colab.research.google.com/assets/colab-badge.svg" width = '' ></a>  |
| 4 | [inspect_ai_tutorial_4_agents.ipynb](inspect_ai_tutorial_4_agents.ipynb)         | Learn how to evaluate autonomous LLM Agents.                     | <a href="https://colab.research.google.com/github/Alg2338/inspect_ai/blob/colab/inspect_ai_tutorial_4_agents.ipynb"><img src="https://colab.research.google.com/assets/colab-badge.svg" width = '' ></a>    |

# Beyond the notebooks

The notebooks cover the core eval loop. A few more building blocks come up on real tasks. Each example below runs in a notebook cell against the default `ollama/llama3.2:3b`.

<details>
<summary>Custom metric</summary>

A metric reduces per-sample scores to one number. Decorate a function that takes the scores and returns a `Value`.

```python
from inspect_ai.scorer import metric, Metric, SampleScore, Value

@metric
def perfect_rate() -> Metric:
    def compute(scores: list[SampleScore]) -> Value:
        vals = [s.score.as_float() for s in scores]
        return sum(1 for v in vals if v == 1.0) / len(vals)
    return compute
```

Add it to any scorer with `metrics=[accuracy(), perfect_rate()]`.
</details>

<details>
<summary>Custom scorer</summary>

A scorer maps model output to a `Score`. This one accepts a numeric answer within a tolerance.

```python
from inspect_ai.scorer import scorer, accuracy, stderr, Score, Target, CORRECT, INCORRECT
from inspect_ai.solver import TaskState

@scorer(metrics=[accuracy(), stderr()])
def within_tolerance(tol: float = 0.5):
    async def score(state: TaskState, target: Target) -> Score:
        num = None
        for tok in state.output.completion.replace(",", "").split():
            try:
                num = float(tok.strip("."))
            except ValueError:
                continue
        ok = num is not None and abs(num - float(target.text)) <= tol
        return Score(value=CORRECT if ok else INCORRECT, answer=str(num))
    return score
```
</details>

<details>
<summary>Custom solver</summary>

A solver controls how the model reaches an answer. This one generates, then asks the model to re-check.

```python
from inspect_ai.solver import solver, TaskState, Generate
from inspect_ai.model import ChatMessageUser

@solver
def double_check():
    async def solve(state: TaskState, generate: Generate) -> TaskState:
        state = await generate(state)
        state.messages.append(
            ChatMessageUser(content="Double-check and reply with only the final number.")
        )
        return await generate(state)
    return solve
```

Drop it into a `Task` as `solver=double_check()`.
</details>

<details>
<summary>Token logprobs</summary>

Request per-token logprobs to read how confident the model was. Providers such as Ollama and OpenAI return them.

```python
from inspect_ai.model import get_model, GenerateConfig

model = get_model("ollama/llama3.2:3b")
out = await model.generate(
    "The capital of France is",
    config=GenerateConfig(logprobs=True, top_logprobs=5, max_tokens=1),
)
for tok in out.choices[0].logprobs.content[0].top_logprobs:
    print(tok.token, round(tok.logprob, 2))
# Paris -0.07
# ...   -3.18
```
</details>

<details>
<summary>Multiple agents</summary>

Run several agents in one flow. A solver agent drafts an answer, then a reviewer agent corrects it.

```python
from inspect_ai.agent import agent, run, AgentState
from inspect_ai.model import get_model, ChatMessageUser, ChatMessageSystem

MODEL = "ollama/llama3.2:3b"

@agent
def solver_agent():
    async def execute(state: AgentState) -> AgentState:
        state.messages.insert(0, ChatMessageSystem(content="Solve the problem. Show the final answer."))
        state.output = await get_model(MODEL).generate(state.messages)
        state.messages.append(state.output.message)
        return state
    return execute

@agent
def reviewer_agent():
    async def execute(state: AgentState) -> AgentState:
        state.messages.append(ChatMessageUser(
            content="Review the answer above. Reply with only the corrected final number."))
        state.output = await get_model(MODEL).generate(state.messages)
        state.messages.append(state.output.message)
        return state
    return execute

state = AgentState(messages=[ChatMessageUser(content="What is 12 * (3 + 4)?")])
state = await run(solver_agent(), state)
state = await run(reviewer_agent(), state)
print(state.output.completion)  # 84
```

For a supervisor that routes to specialist agents, see `handoff()` in the [agents docs](https://inspect.aisi.org.uk/agents.html). Routing needs a tool-capable model, so it runs slowly on small local ones.
</details>

# FAQ

<details>
<summary>How much memory does it take to run local models?</summary>

On CPU, for ollama:

| Model            | Context window (by default in ollama) (tokens) | RAM (est.) |
|------------------|------------------------------------------------|------------|
| llama 3 8B       | 4096                                           | 5.5 GB     |
| qwen 2.5 3B      | 4096                                           | 2.3 GB     |
| deepseek-r1 1.5B | 4096                                           | 1.6 GB     |

To estimate the memory usage for other models, you can try using them yourself or use the corresponding formulas.

</details>

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
<summary>Why are some cells slow?</summary>    

It takes some time (especially when using local models, e.g. with Ollama) to run the `eval()` function. So don't rerun these cells if it is not necessary. Also, you can use fewer examples via the `eval(limit=1)` param to test your setup.
</details>

<details>
<summary>My eval hangs or runs forever. What can I do?</summary>

This usually happens with slow local models or long agent loops. Pass limits to `eval()`: `limit=10` runs only the first few samples, `max_connections=2` caps how many requests run in parallel (lower it for local models), `timeout=120` gives up on a request that has stopped responding, and `message_limit=20` stops runaway agent loops. To bound a sample that never finishes, `time_limit` sets a per-sample wall-clock cap; keep it well above how long one sample should legitimately take, since a slow local model or a long agent run can need several minutes each. Check a stuck run in `inspect view` before rerunning it.
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
<summary>How to use <tt>multiple_choice()</tt> solver? How to make multiple choice question with CoT?</summary>

The `multiple_choice()` solver formats the multiple-choice prompt and calls `generate()` internally, so do not add a separate `generate()` after it. Pre-solvers such as `system_message()` can still be placed before `multiple_choice()`. Use `choice()` as the scorer.

You can also customize the prompt using the `template` parameter. For additional help, [check the docs](https://inspect.aisi.org.uk/reference/inspect_ai.solver.html#multiple_choice). 

DO NOT stack `chain_of_thought()` + `multiple_choice()`.
</details>

<details>
<summary>How do agents use resource? Do they only use the last message?</summary>

Agents use a lot of resources: each message, each tool call result, and each scaffold message is in the context window. The context window cannot be infinitely long: LLMs by design are constrained by a fixed context window size.

For a local model, the dependency is linear: for example, running Llama 3 (8B) on a CPU costs 0.5 GB of RAM for every 4,096 tokens of maximum context size, up to ~130k tokens, in addition to 4.8 GB of model weights. (Ollama allocates all the memory at once at the beginning of the model run.)

CPU LLM engines (e.g., Ollama) take more memory with each new generated token, and it takes more time to generate each new token as well (because CPU RAM is very slow).

Tip: Models are prone to forgetting information from the middle of their context. Therefore, the effective context is much smaller than the maximum. Increasing the context window and the number of messages probably won't be very effective.

</details>

## Contact us

If you have any questions, comments, ideas, or feedback—including ideas for extending the existing notebooks or creating new ones on this or entirely different topics—feel free to come chat with us on [Discord](https://discord.gg/GPnm8GSCy), or contact me via [email](mailto:alexgorb2002@gmail.com).

