param(
  [Parameter(Mandatory=$true)][string]$Folder,
  [Parameter(Mandatory=$true)][string]$Title,
  [Parameter(Mandatory=$true)][string]$PlaylistFile,
  [string]$DbPath = "F:\\Engine Library\\Database2\\m.db",
  [string]$MusicRoot = "F:\\Music",
  [switch]$DryRun
)

$py = "python"
$script = "F:\Music\tools\engine_playlist_db.py"

$args = @(
  $script,
  "--db", $DbPath,
  "--music-root", $MusicRoot,
  "--folder", $Folder,
  "--title", $Title
)

switch -Regex ($PlaylistFile) {
  '\.m3u8?$' { $args += @("--m3u", $PlaylistFile); break }
  '\.csv$'  { $args += @("--csv", $PlaylistFile); break }
  default   { throw "Неподдерживаемый формат: $PlaylistFile (нужно .m3u/.m3u8 или .csv)" }
}

if ($DryRun) { $args += "--dry-run" }

& $py @args
exit $LASTEXITCODE

