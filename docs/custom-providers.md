[< Back to README](../README.md) | [Prerequisites](prerequisites.md) | [Setup](setup.md) | [How It Works](how-it-works.md) | [Configuration](configuration.md) | [API Spec](api-spec.md)

---

# Adding Custom Providers

Auto Developer uses a pluggable adapter pattern. Every provider type has a base class that validates your implementation at startup — missing methods throw immediately, not at runtime.

---

## Provider Types

| Type | Base Class | Required Methods | Example Adapters |
|------|-----------|-----------------|-----------------|
| Issue Tracker | `IssueTrackerBase` | `name`, `eventLabel`, `parseWebhook()` | Jira, GitHub Issues |
| Git Provider | `GitProviderBase` | `name`, `prLabel`, `parseWebhook()`, `createApi()` | GitLab, GitHub |
| CLI Adapter | `CliAdapterBase` | `name`, `label`, `defaultCommand`, `buildArgs()`, `parseOutput()` | Claude Code, Codex, Gemini |
| Notification | `NotificationBase` | `name`, `label`, `send()` | Slack |

---

## Adding a New Issue Tracker (e.g. Linear)

### 1. Create the adapter

`src/providers/trackers/linear.js`:

```js
const { IssueTrackerBase } = require('../base/issue-tracker-base');

class LinearAdapter extends IssueTrackerBase {
  get name() { return 'linear'; }
  get eventLabel() { return 'issue'; }

  parseWebhook(headers, payload, config) {
    // Linear sends webhooks with action: 'update' and data.state
    if (payload.action !== 'update') return null;
    if (payload.data?.state?.name !== config.triggerStatus) return null;

    return {
      issueKey: payload.data?.identifier || '',     // e.g. 'LIN-42'
      summary: payload.data?.title || '',
      component: payload.data?.team?.name || null,
    };
  }
}

module.exports = new LinearAdapter();
```

### 2. Register in factory

`src/providers/issue-tracker.js` — add a case:

```js
case 'linear':
  adapter = require('./trackers/linear');
  break;
```

### 3. Configure

```yaml
issueTracker:
  type: linear
  triggerStatus: In Progress
  doneStatus: Done
```

---

## Adding a New Git Provider (e.g. Bitbucket)

### 1. Create the adapter

`src/providers/git/bitbucket.js`:

```js
const axios = require('axios');
const { GitProviderBase } = require('../base/git-provider-base');

class BitbucketAdapter extends GitProviderBase {
  get name() { return 'bitbucket'; }
  get prLabel() { return 'pull request'; }

  parseWebhook(headers, payload, config) {
    const event = headers['x-event-key'];
    // Handle: pullrequest:approved, repo:push, pullrequest:comment_created
    // Return: { event: 'approved'|'push'|'comment', branch, prId, author }
  }

  createApi(env) {
    // Return object with all 8 methods:
    // createBranch, commitFiles, createPR, getPR, updatePR,
    // listPRComments, postPRComment, getFile
    const api = { /* ... */ };
    this.validateApi(api);  // built-in validation
    return api;
  }
}

module.exports = new BitbucketAdapter();
```

### 2. Register + add MCP server

- Add `case 'bitbucket':` in `src/providers/git-provider.js`
- Optionally create `mcp-servers/bitbucket/` so agents can use git tools

### 3. Configure

```yaml
gitProvider:
  type: bitbucket
  botUsers:
    - atlassian-bot
```

---

## Adding a New CLI Adapter (e.g. Aider)

### 1. Create the adapter

`src/providers/cli/aider.js`:

```js
const { CliAdapterBase } = require('../base/cli-adapter-base');

class AiderAdapter extends CliAdapterBase {
  get name() { return 'aider'; }
  get label() { return 'Aider CLI'; }
  get defaultCommand() { return 'aider'; }

  buildArgs(agentName, input, config) {
    return ['--message', `[Agent: ${agentName}]\n${input}`, '--yes-always'];
  }

  parseOutput(stdout, stderr, exitCode) {
    return {
      success: exitCode === 0,
      output: stdout,
      error: exitCode !== 0 ? stderr : null,
    };
  }
}

module.exports = new AiderAdapter();
```

### 2. Register

Add `case 'aider':` in `src/providers/cli-adapter.js`

### 3. Configure

```yaml
cliAdapter:
  type: aider
```

---

## Adding a New Notification Provider (e.g. Microsoft Teams)

### 1. Create the adapter

`src/providers/notifications/teams.js`:

```js
const { NotificationBase } = require('../base/notification-base');
const axios = require('axios');

class TeamsAdapter extends NotificationBase {
  get name() { return 'teams'; }
  get label() { return 'Microsoft Teams'; }

  async send(message, config) {
    // Post to Teams webhook URL
    await axios.post(config.webhookUrl, {
      text: message,
    });
  }
}

module.exports = new TeamsAdapter();
```

### 2. Register

Add `case 'teams':` in `src/providers/notification.js`

### 3. Configure

```yaml
notification:
  type: teams
  webhookUrl: https://outlook.office.com/webhook/...
```

---

## Base Class Validation

All base classes validate at construction time:

```
IssueTrackerBase → requires: name, eventLabel
GitProviderBase  → requires: name, prLabel + validateApi() checks 8 methods
CliAdapterBase   → requires: name, label, defaultCommand
NotificationBase → requires: name, label
```

If you forget to implement a required method, you get an error at startup:

```
Error: MyAdapter: must implement parseWebhook()
```

Not at runtime when a webhook arrives. Fail fast.
