# Using WeCFU 1.2.0

The current workflow is described in [README.md — Review and export](README.md#review-and-export).
For installation, model setup, cache selection and troubleshooting, use
[INSTALL.md](INSTALL.md).

Opening a photo does not start model inference. Declare the photo's view,
request the selected method, review candidates and apply them explicitly.
Local workspaces persist; hosted sessions are temporary and should be exported
before you leave. Default Fusion v2 reports unavailable models and execution
errors without silently selecting a different algorithm.
