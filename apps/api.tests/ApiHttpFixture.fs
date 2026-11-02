namespace RNGWars.Api.Tests

open System
open System.Diagnostics
open System.IO
open System.Net.Http
open System.Text
open System.Threading.Tasks

type ApiHttpFixture(?configuration: (string * string) list) =
    let directory = Path.Combine(Path.GetTempPath(), "rngwars-http-" + Guid.NewGuid().ToString("N"))
    let name = "rngwars-http-" + Guid.NewGuid().ToString("N")
    let logs = StringBuilder()
    let mutable child: Process option = None
    let mutable localUrl = ""
    let mutable privateUrl = ""
    let client = new HttpClient(Timeout = TimeSpan.FromSeconds(15.0))
    let append (line: string) =
        if not (isNull line) then
            lock logs (fun () -> logs.AppendLine(line) |> ignore)
            if line.StartsWith("FIXTURE_URLS ") then
                let urls = line.Substring(13).Split(' ', StringSplitOptions.RemoveEmptyEntries)
                if urls.Length = 2 then
                    localUrl <- urls[0]
                    privateUrl <- urls[1]

    do Directory.CreateDirectory(directory) |> ignore

    member _.Logs = lock logs (fun () -> logs.ToString())
    member _.LocalUrl = localUrl
    member _.PrivateUrl = privateUrl
    member _.DatabasePath = Path.Combine(directory, "game.db")
    member _.LocalDatabaseExists = File.Exists(Path.Combine(directory, "game.db"))
    member _.LastExitCode = child |> Option.filter (fun p -> p.HasExited) |> Option.map (fun p -> p.ExitCode)

    member _.Stop() =
        match child with
        | Some p ->
            if not p.HasExited then
                use signal = Process.Start("kill", $"-TERM {p.Id}")
                signal.WaitForExit()
                if not (p.WaitForExit(10000)) then
                    p.Kill(true)
                    p.WaitForExit()
            p.Dispose()
            child <- None
        | None -> ()

    member this.Start() = task {
        this.Stop()
        localUrl <- ""
        privateUrl <- ""
        let info = ProcessStartInfo("portless", RedirectStandardOutput = true, RedirectStandardError = true, UseShellExecute = false)
        info.WorkingDirectory <- directory
        for arg in [ "--name"; name; "--tailscale"; "bash"; "-c"
                     "printf 'FIXTURE_URLS %s %s\\n' \"$PORTLESS_URL\" \"$PORTLESS_TAILSCALE_URL\"; exec \"$RNGWARS_TEST_DOTNET\" \"$RNGWARS_TEST_API\" --urls \"http://127.0.0.1:$PORT\"" ] do
            info.ArgumentList.Add(arg)
        let allowed = set [ "PATH"; "HOME"; "USER"; "LOGNAME"; "TMPDIR"; "LANG"; "XDG_RUNTIME_DIR"
                            "SSL_CERT_FILE"; "SSL_CERT_DIR"; "DOTNET_ROOT"; "DOTNET_ROOT_X64"
                            "PORTLESS_PORT"; "PORTLESS_STATE_DIR"; "PORTLESS_HTTPS" ]
        for key in info.Environment.Keys |> Seq.toArray do
            if not (allowed.Contains(key)) then info.Environment.Remove(key) |> ignore
        info.Environment["PORTLESS_LAN"] <- "0"
        info.Environment["PORTLESS_FUNNEL"] <- "0"
        info.Environment["PORTLESS_NGROK"] <- "0"
        info.Environment["ASPNETCORE_ENVIRONMENT"] <- "Development"
        info.Environment["RNGWARS_TEST_DOTNET"] <-
            Environment.GetEnvironmentVariable("RNGWARS_TEST_DOTNET")
            |> Option.ofObj
            |> Option.defaultValue (Path.GetFullPath(Path.Combine(System.Runtime.InteropServices.RuntimeEnvironment.GetRuntimeDirectory(), "../../../dotnet")))
        info.Environment["RNGWARS_TEST_API"] <- typeof<RNGWars.Models.User>.Assembly.Location
        info.Environment["DATABASE_PATH"] <- Path.Combine(directory, "game.db")
        for key, value in defaultArg configuration [] do info.Environment[key] <- value
        let p = new Process(StartInfo = info)
        p.OutputDataReceived.Add(fun e -> append e.Data)
        p.ErrorDataReceived.Add(fun e -> append e.Data)
        p.Start() |> ignore
        child <- Some p
        p.BeginOutputReadLine()
        p.BeginErrorReadLine()
        let deadline = DateTime.UtcNow.AddSeconds(45)
        let mutable ready = false
        while not ready && not p.HasExited && DateTime.UtcNow < deadline do
            if localUrl <> "" && privateUrl <> "" then
                try
                    use! response = client.GetAsync(localUrl + "/api/health")
                    ready <- response.IsSuccessStatusCode
                with
                | :? HttpRequestException -> ()
                | :? TaskCanceledException -> ()
            if not ready then do! Task.Delay(100)
        if localUrl = "" || privateUrl = "" then
            failwith "Portless/private Tailscale unavailable: API child was not launched (logs withheld; inspect Portless infrastructure)."
        if not ready && not p.HasExited then
            failwith "API startup timed out; this is not evidence of a rejected configuration."
        if not ready && p.ExitCode = 0 then
            failwith "API exited successfully without serving HTTP; expected startup failure must be nonzero."
        if ready then
            use listing = Process.Start(ProcessStartInfo("portless", "list", RedirectStandardOutput = true))
            let! routes = listing.StandardOutput.ReadToEndAsync()
            do! listing.WaitForExitAsync()
            if not (routes.Contains(localUrl) && routes.Contains(privateUrl)) then
                failwith "Portless did not register both fixture endpoints (logs withheld)."
            use! shared = client.GetAsync(privateUrl + "/api/health")
            if not shared.IsSuccessStatusCode then failwith "Private Tailscale fixture health check failed."
            printfn "Temporary API fixture endpoints: %s (local), %s (private Tailscale)" localUrl privateUrl
        return ready
    }

    member _.Request(method: HttpMethod, path: string, ?token: string, ?body: string) = task {
        use request = new HttpRequestMessage(method, localUrl + path)
        token |> Option.iter (fun value -> request.Headers.Authorization <- Headers.AuthenticationHeaderValue("Bearer", value))
        body |> Option.iter (fun value -> request.Content <- new StringContent(value, Encoding.UTF8, "application/json"))
        return! client.SendAsync(request)
    }

    interface IDisposable with
        member this.Dispose() =
            this.Stop()
            client.Dispose()
            Microsoft.Data.Sqlite.SqliteConnection.ClearAllPools()
            Directory.Delete(directory, true)
