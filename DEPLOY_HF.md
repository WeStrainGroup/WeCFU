# Hugging Face deployment

The existing Docker Space is [WeCFU/wecfu](https://huggingface.co/spaces/WeCFU/wecfu).
Use the deployment procedure in [SHARE.md](SHARE.md). It preserves the existing
Space history, prepares the pinned CPU model cache during the image build, and
uses README_HF.md as the Space's README. Do not force-push or upload a private
workspace. A successful Git push alone does not confirm a successful deployment.
