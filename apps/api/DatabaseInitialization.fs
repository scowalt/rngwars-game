namespace RNGWars

open System
open System.IO
open System.Runtime.InteropServices

module DatabaseInitialization =
    [<DllImport("libc", EntryPoint = "geteuid")>]
    extern uint32 private effectiveUserId()

    [<Struct; StructLayout(LayoutKind.Sequential, Size = 256)>]
    type private FileStatus =
        val mutable Mask: uint32
        val mutable BlockSize: uint32
        val mutable Attributes: uint64
        val mutable Links: uint32
        val mutable Owner: uint32
        val mutable Group: uint32
        val mutable Mode: uint16

    [<DllImport("libc", EntryPoint = "statx", CharSet = CharSet.Ansi)>]
    extern int private fileStatus(int directory, string path, int flags, uint32 mask, FileStatus& status)

    let private inspect path =
        let mutable status = Unchecked.defaultof<FileStatus>
        if fileStatus(-100, path, 0x100, 0xFu, &status) <> 0 || status.Mask &&& 0xFu <> 0xFu then
            invalidOp "Storage ownership and type must be verifiable."
        status

    let private privateMode = UnixFileMode.UserRead ||| UnixFileMode.UserWrite ||| UnixFileMode.UserExecute

    let private privateParent path =
        if String.IsNullOrWhiteSpace(path) || not (Path.IsPathFullyQualified(path)) || Path.GetFullPath(path) <> path then
            invalidOp "An explicit canonical absolute database path is required."
        if not (OperatingSystem.IsLinux()) || effectiveUserId() = 0u then
            invalidOp "Initialize on Linux as the non-root data owner."
        let owner = effectiveUserId()
        let parent = Path.GetDirectoryName(path: string)
        let mutable current = DirectoryInfo(parent)
        while not (isNull current) do
            let status = inspect current.FullName
            if status.Mode &&& 0xF000us <> 0x4000us || (status.Owner <> 0u && status.Owner <> owner) then
                invalidOp "Storage ancestors must be real directories owned by root or the data owner."
            let writableByOthers = status.Mode &&& 0x12us <> 0us
            let rootSticky = status.Owner = 0u && status.Mode &&& 0x200us <> 0us
            if writableByOthers && not rootSticky then invalidOp "Storage ancestors must not be replaceable by other users."
            current <- current.Parent
        if (inspect parent).Owner <> owner || File.GetUnixFileMode(parent) <> privateMode then
            invalidOp "An existing private data-owner directory is required."
        parent

    let private requireAbsent path =
        for suffix in [ ""; "-wal"; "-shm"; "-journal" ] do
            let candidate = path + suffix
            if File.Exists(candidate) || Directory.Exists(candidate) || not (isNull (FileInfo(candidate).LinkTarget)) then
                invalidOp "Database destination and sidecars must not exist."

    let initialize (path: string) =
        let parent = privateParent path
        requireAbsent path
        let staging = Path.Combine(parent, ".rngwars-initialize-" + Guid.NewGuid().ToString("N"))
        Directory.CreateDirectory(staging, privateMode) |> ignore
        try
            let staged = Path.Combine(staging, "game.db")
            let fileMode = UnixFileMode.UserRead ||| UnixFileMode.UserWrite
            let options = FileStreamOptions(Mode = FileMode.CreateNew, Access = FileAccess.ReadWrite, Share = FileShare.None)
            options.UnixCreateMode <- Nullable fileMode
            do
                use reserved = new FileStream(staged, options)
                ()
            Database.initializeAtPath staged
            let completedStatus = inspect staged
            if completedStatus.Owner <> effectiveUserId() || completedStatus.Mode <> 0x8180us || completedStatus.Links <> 1u
               || Directory.GetFileSystemEntries(staging).Length <> 1 then
                invalidOp "Initialized database must be private and have no remaining sidecars."
            do
                use completed = new FileStream(staged, FileMode.Open, FileAccess.ReadWrite, FileShare.None)
                completed.Flush(true)
            privateParent path |> ignore
            requireAbsent path
            File.Move(staged, path, false)
        finally
            Directory.Delete(staging, true)
