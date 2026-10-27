# Git hooks

`pre-push` runs the backend tests and the frontend typecheck and lint before every push.

Enable once per clone:

```bash
git config core.hooksPath .githooks
```
