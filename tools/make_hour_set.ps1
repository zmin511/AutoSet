$BundledPython = "C:\Users\inasonov\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
$Script = "G:\zmin_autoset\tools\engine_set_builder.py"

if (-not (Test-Path -LiteralPath $BundledPython)) {
  throw "Bundled Python was not found: $BundledPython"
}
if (-not (Test-Path -LiteralPath $Script)) {
  throw "Set builder script was not found: $Script"
}

& $BundledPython $Script @args
