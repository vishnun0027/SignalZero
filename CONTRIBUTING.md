# Contributing to SignalZero

First off, thank you for considering contributing to SignalZero! It's people like you that make open source such a great community.

## Where do I go from here?

If you've noticed a bug or have a feature request, make one! It's generally best if you get confirmation of your bug or approval for your feature request this way before starting to code.

## Fork & create a branch

If this is something you think you can fix, then fork SignalZero and create a branch with a descriptive name.

## Get the test suite running

Make sure you install the development dependencies using `uv` and run the tests to ensure everything is working locally.

```bash
uv sync --all-extras
uv run pytest
```

## Implement your fix or feature

At this point, you're ready to make your changes. Feel free to ask for help; everyone is a beginner at first.

## Make a Pull Request

At this point, you should switch back to your master branch and make sure it's up to date with SignalZero's master branch.
Then create a Pull Request with a clear description of the changes you've made.
