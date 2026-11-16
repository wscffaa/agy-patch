<!-- Adapted from deepseek-ai/deepseek-harness (MIT): .agents/notes/README.zh.md -->
# Agent Notes

[English](README.md) | 中文

这里存放一类设计文档。**Agent Note** 记录影响本代码库的决策或提案：代码和文档无法承载的*为什么*以及*放弃了什么*。本文件规定 Agent Note 存放在哪里、何时需要写一份，以及[文件内格式](#the-file-format)。

## 布局与命名

每份 Agent Note 有两个维度，都编码在其**路径**中：`{lifecycle}/{class}/yyyy-mm-dd-topic-title.md`。

- **生命周期**（顶层文件夹）是 Agent Note 的状态，Agent Note 随状态变化在文件夹之间移动：
  - **`proposed/`**：实施前评审的提案；尚未构建（或仅部分构建）。
  - **`implemented/`**：决策已交付。文件记录做了什么决定、否决了什么，并与实际交付的内容保持同步：代码后续移动文件、重命名包或更改键名、默认值时，Agent Note 在同一变更中同步更新，且仅限事实（路径、名称、结构），不改动决策本身。见 [implemented/AGENTS.md](implemented/AGENTS.md)。
  - **`rejected/`**：提案经讨论后被否决。仅当其决策依据仍能避免一种诱人且影响重大的错误时保留；否则删除完整三文件组。
- **类别**（嵌套文件夹）是决策的*种类*，见下方[分类](#classification)。

文件名中的日期是该主题**首次提出**的时间（以 git 历史为准）。Agent Note 之间的交叉引用使用相对 Markdown 链接（`[topic](../../implemented/architecture/2026-…-….md)`），不使用纯文字，这样门禁可以检查，文件夹间移动后链接也不会失效。

活跃生命周期目录树就是工作清单：浏览其生命周期或类别文件夹，或搜索仓库即可。请勿添加集中式 `INDEX.md`：它重复路径元数据，并让无关记录的变更争用同一个生成文件。具有历史价值但未来指导价值较低的已实施记录，移入单独冻结的 [`archived/`](archived/AGENTS.md) 目录树。

## <a id="classification"></a>分类

每份 Agent Note 属于 `agent-note-format` 门禁强制执行的封闭类别集合中的一个路径类别，门禁拒绝其他文件夹。新增类别需要同时更新规范集合与本节。

| 类别 | 覆盖范围 |
|---|---|
| `feature` | 面向用户或模型的新能力。 |
| `bug-fix` | 修正缺陷，或弥补事故复盘发现的缺口。 |
| `simplification` | 在不增加能力的前提下移除代码、行为或对外范围。 |
| `architecture` | 关于**交付源码**的结构性决策：模块之间的关系、运行时词汇。 |
| `process` | 代码**周边**的工具、策略或工作流：门禁、包管理器、vendor 化。不涉及运行时行为。 |
| `testing` | 测试基础设施与策略。 |

`architecture` 与 `process` 的界线：**architecture** 关乎我们交付的源码；**process** 关乎围绕源码的工具与工作流。（`refactor` 被有意排除：它与 `simplification` 重叠，而后者的判别标准「可观察行为是否改变」已经覆盖了它。）

## 归档与删除

仅描述小型 UI 调整或纯机械变更的 implemented Agent Note 直接删除，并一并删除英文、中文和伴随记录文件，修复或移除入站链接。局部 bug 修复、性能变更、新能力或实质行为决策，不会仅因实现规模小就符合删除条件。其他已实施记录只有在交付决策已完整落地、其依据不太可能再指导未来工作、但仍具有历史价值时才归档。如果其中的备选方案、归属边界、否定性保证、持久化或协议语义、安全规则，或重新引入条件仍有价值，则继续作为活跃记录保留。绝不归档 proposed Agent Note：过时的提案应转为 rejected。仅当 rejected Agent Note 仍能避免一种可能发生的错误时保留。请使用经过校准的 `tianshu-archive-agent-notes` 技能工作流，不要根据字数、存续时间或目标配额判断。

归档路径编码为 `archived/{class}/yyyy-mm-dd-topic-title.md`，其中有意省略 `implemented`，因为只有 implemented Agent Note 可以进入归档。归档变更会移动完整的英文、中文和伴随记录三个文件，保留 `Status: implemented`，在两种语言的文件中紧接该状态行插入相同的 `Archived: YYYY-MM-DD` 行，重新记录伴随记录，并修复或删除入站链接。归档时只允许做这些内容更改。归档后运行 `archived-agent-notes` 门禁：`npm --prefix scripts/tianshu run gate -- archived-agent-notes --repo "$PWD"`。

封存后，每组归档文件永久冻结。禁止编辑、翻译、重新格式化、更新、移动或删除，也不得将其视为当前行为的权威依据。当活跃文档有意引用历史时，仍可链接到归档 Agent Note。

<a id="何时需要写一份"></a>

## 何时需要写一份

只有代码、测试和现有文档无法解释、且具有长期价值的决策理由，才在同一 PR 中新增或更新 Agent Note。对未来重大工作的提案从 `proposed/` 开始；已经做出的决策从 `implemented/` 开始。选择与决策匹配的类别文件夹。

更新已经拥有该决策的 Agent Note 即可满足规则，不要创建重复记录。机械性或局部编辑均可豁免，包括局部 UI 展示和交互调整。Agent Note 不得被编辑成*另一个决策*：用新 Agent Note 取代旧记录，并让两者互相链接，除非后续按下方规则完全合并旧记录。

被完全取代的 implemented Agent Note 可以合并到当前持有该决策的记录中，然后删除原文件。删除前，当前记录必须保存所有独有的决策依据、备选方案、影响、必需的验证和明确指出的覆盖缺口；修复所有入站链接；并在同一变更中删除中文对侧文件。仅部分被取代的记录不符合此条件：保留两个记录并让它们互相链接，同时更新所有仍然适用的事实。合并不得将旧文件改写成与其相反的决策，也不得让 git 历史成为决策依据的唯一副本。

## <a id="the-file-format"></a>文件格式

每份活跃 Agent Note 遵循统一的文件内格式，由 `agent-note-format` 门禁强制执行：

```sh
npm --prefix scripts/tianshu run gate -- agent-note-format --repo "$PWD"
```

归档记录保留封存时的格式，并增加上述归档日期行。

### 头部块

每份 Agent Note 的前三行严格为：

```markdown
# Agent Note: <title>

Status: <status>
```

后跟一个空行。`Status:` 的值有三种形式，且必须与文件所在的生命周期文件夹一致，门禁会交叉检查：

- `Status: proposed`
- `Status: implemented`
- `Status: rejected — <why, in one line>`

状态行不带日期，也不带括号补充说明：文件名记录首次提出日期，git 记录其余内容。拒绝原因是唯一带内容的状态，因为读者查阅被否决的 Agent Note 时，结论正是他们要找的。

### 正文骨架

每份 Agent Note 的正文以 `## Problem` 开头：动机，写法上不依赖解决方案即可独立成文。后续内容取决于生命周期。固定章节使用以下规范名称且仅限这些名称；真正独特的技术章节（包拓扑、协议约定、schema 等）可在必需章节之间自由组织。

#### `proposed/`

```markdown
## Problem
## Proposal
…bespoke sections…
## Alternatives considered
## Acceptance criteria
## Risks
```

`## Proposal` 描述拟议的变更，可以使用将来时态。`## Acceptance criteria` 说明什么可观察状态意味着完成。`## Risks` 涵盖可能出错的事项，以及该变更有意放弃的东西。

#### `implemented/`

```markdown
## Problem
## Decision
…bespoke sections…
## Alternatives considered
## Consequences
```

`## Decision` 以现在时态描述已交付的现实，整个文件按 [implemented/AGENTS.md](implemented/AGENTS.md) 的要求与之保持同步。`## Consequences` 记录权衡的代价**与**收益。提案阶段的标题在此属于规格用语，门禁会拒绝：`## Proposal`、`## Plan`、`## Migration plan` 和 `## Acceptance criteria` 不得出现在 implemented Agent Note 中。`## Testing`、`## Deferred` 或 `## Related` 章节在陈述现在时态的事实时是允许的。

#### `rejected/`

被否决的 Agent Note 是冻结的提案：保留提案时的所有章节，结论写在 `Status:` 行上。仅头部块、`## Problem` 开头、`## Proposal` 章节以及下方的「曾考虑的替代方案」强制适用。

### 曾考虑的替代方案：必需

每份 Agent Note 都必须包含 `## Alternatives considered` 章节：每个真实的替代方案及其落选原因，每个替代方案用一个加粗引导的段落，或对争议较大的替代方案用 `### Why not <X>?` 子节。记录决策时不记录它击败了什么，就是在邀请反复争论，这正是 Agent Note 旨在防止的问题。

替代方案是记录下来的，不是凭空编造的。无法从记录中重建替代方案的 Agent Note，用以下精确注释代替该章节。门禁仅对格式规范之前的文件接受此注释：

```markdown
<!-- agent-note-format: alternatives-not-recorded (pre-format Agent Note) -->
```

### 在生命周期之间移动

将文件在生命周期文件夹之间移动，意味着在同一变更中更新 `Status:` 行并满足目标文件夹的骨架要求，否则门禁会失败。`proposed/` → `implemented/` 将 `## Proposal` 改写为现在时态的 `## Decision`，将 `## Acceptance criteria` 和 `## Risks` 折入 `## Consequences`（或折入现在时态的 `## Testing` 章节），并用实际交付的内容替换计划。`proposed/` → `rejected/` 仅在 `Status:` 行添加原因并冻结文件。

### 中文对侧文件

`.zh.md` 对侧文件按[文档标准](../../docs/AGENTS.md)逐章节与其英文对侧文件保持相同结构。机器检查的头部标记（`# Agent Note: ` 和 `Status:` 行）保持英文原样。格式门禁跳过 `.zh.md` 文件；配对门禁检查它们的一致性：

```sh
npm --prefix scripts/tianshu run gate -- translation-pairing --repo "$PWD" --staged
```
