# Local model placement

Model weights are deliberately not stored in Git.  Place the complete
Transformers model directory at `models/Qwen3-0.6B`, or pass another local
path to `app/run.ps1 -ModelPath`.

The hardware validation used `Qwen/Qwen3-0.6B`.  Its local
`model.safetensors` was 1,503,300,328 bytes with SHA-256:

```text
F47F71177F32BCD101B7573EC9171E6A57F4F4D31148D38E382306F42996874B
```

Obtain model files from their publisher under the applicable model licence;
the application never downloads or modifies them automatically.
