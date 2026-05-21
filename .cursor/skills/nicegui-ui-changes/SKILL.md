---
name: nicegui-ui-changes
description: Fetches the concise, opinionated guide for AI assistants working with NiceGUI before modifying UI code in app/ui/. Use whenever editing, creating, refactoring, or reviewing any file under app/ui/ in this project.
---

# NiceGUI UI Changes

Before making ANY change to files under `app/ui/`, fetch and read the NiceGUI reference:

```
https://nicegui.io/llms.txt
```

Use the `WebFetch` tool (or equivalent) to retrieve it, then apply the patterns and APIs documented there to the change you are about to make.

Do this once per session before the first edit to `app/ui/`. If you have already fetched it in the current session, you do not need to fetch it again.
