## Installation

### Clone HydroAgent

HydroAgent uses a customized SYMFLUENCE checkout as its hydrological modelling backend. That checkout is a Git submodule at `symfluence/`, linked to [uofs-simlab/SYMFLUENCE-HydroAgent](https://github.com/uofs-simlab/SYMFLUENCE-HydroAgent) on the `hydroagent-v2` branch.

Clone HydroAgent and the submodule together:

```bash
git clone --recurse-submodules https://github.com/uofs-simlab/HydroAgent.git
cd HydroAgent
```

After cloning, the repository should look like:

```
HydroAgent/
├── app/
├── ...
├── .gitmodules
└── symfluence/          # HydroAgent-compatible SYMFLUENCE submodule
```

If `symfluence/` is empty, the submodule was not initialized. Use the command in [If HydroAgent was already cloned](#if-hydroagent-was-already-cloned).

Point HydroAgent at this checkout in `~/.symfluence_assistant/config.yaml`:

```yaml
symfluence_repo: /absolute/path/to/HydroAgent/symfluence
```

Do not clone upstream [symfluence-org/SYMFLUENCE](https://github.com/symfluence-org/SYMFLUENCE) for use with HydroAgent. The submodule is the supported backend.

### If HydroAgent was already cloned

If you cloned without `--recurse-submodules`, initialize the submodule from the HydroAgent root:

```bash
git submodule update --init --recursive
```

### Updating an existing clone

```bash
git pull
git submodule update --init --recursive
```

`git pull` updates HydroAgent only. The second command checks out the SYMFLUENCE commit that this HydroAgent revision expects.

### Cloning a specific branch

To clone the Version 2 development branch together with its submodule:

```bash
git clone --branch version-2 --recurse-submodules \
    https://github.com/uofs-simlab/HydroAgent.git
cd HydroAgent
```

This is the recommended way to obtain HydroAgent Version 2.
