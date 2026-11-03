namespace RNGWars

open System
open System.Globalization
open System.IO
open System.Text.RegularExpressions
open Microsoft.Data.Sqlite

module internal SqliteSchema =
    let freshApplicationId = 0x524E4757

    let private assembly = typeof<Models.User>.Assembly

    let private scripts =
        assembly.GetManifestResourceNames()
        |> Array.filter (fun name -> name.Contains(".migrations.") && name.EndsWith(".sql"))
        |> Array.sort

    let private rows (connection: SqliteConnection) sql =
        use command = connection.CreateCommand()
        command.CommandText <- sql
        use reader = command.ExecuteReader()
        [ while reader.Read() do
            yield [ for index in 0 .. reader.FieldCount - 1 do
                        yield if reader.IsDBNull(index) then None else Some (reader.GetValue(index).ToString()) ] ]

    let private sqlTokens text =
        Regex.Matches(text, """--[^\n]*|/\*[\s\S]*?\*/|[xX]'(?:[0-9A-Fa-f]{2})*'|'(?:''|[^'])*'|"(?:""|[^"])*"|`(?:``|[^`])*`|\[[^\]]*\]|0[xX][0-9A-Fa-f](?:_?[0-9A-Fa-f])*|(?:[0-9](?:_?[0-9])*(?:\.(?:[0-9](?:_?[0-9])*)?)?|\.[0-9](?:_?[0-9])*)(?:[eE][+-]?[0-9](?:_?[0-9])*)?|[A-Za-z_$\u0080-\uFFFF][A-Za-z_0-9$\u0080-\uFFFF]*|\|\||->>|->|<<|>>|<=|>=|==|!=|<>|[^\s]""")
        |> Seq.cast<Match>
        |> Seq.map (fun token -> token.Value)
        |> Seq.filter (fun token -> not (token.StartsWith("--", StringComparison.Ordinal) || token.StartsWith("/*", StringComparison.Ordinal)))
        |> Seq.toList

    let private schema connection =
        rows connection "SELECT type, name, tbl_name, sql FROM sqlite_master WHERE tbl_name IN ('users', 'matches') ORDER BY type, name"
        |> List.map (function
            | [ kind; name; table; sql ] -> [ kind; name; table ], Option.map sqlTokens sql
            | _ -> invalidOp "SQLite schema metadata is invalid.")

    let validate (connection: SqliteConnection) requireProduction =
        if rows connection "PRAGMA integrity_check" <> [ [ Some "ok" ] ] then
            invalidOp "SQLite integrity check failed."
        if rows connection "PRAGMA foreign_key_check" <> [] then
            invalidOp "SQLite contains foreign-key violations."
        let tables = rows connection "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
        let hasJournal = tables |> List.exists (fun row -> row = [ Some "SchemaVersions" ])
        if not hasJournal then
            if requireProduction || not tables.IsEmpty then
                invalidOp "SQLite schema is missing its migration journal; manual reconciliation is required."
        else
            let journalColumns = rows connection "SELECT name, type, [notnull], pk FROM pragma_table_info('SchemaVersions') ORDER BY cid"
            if journalColumns <>
                [ [ Some "SchemaVersionID"; Some "INTEGER"; Some "1"; Some "1" ]
                  [ Some "ScriptName"; Some "TEXT"; Some "1"; Some "0" ]
                  [ Some "Applied"; Some "DATETIME"; Some "1"; Some "0" ] ] then
                invalidOp "SQLite migration journal schema is invalid; manual reconciliation is required."
            let journal = rows connection "SELECT ScriptName, Applied FROM SchemaVersions ORDER BY ScriptName"
            let applied =
                journal |> List.map (function
                    | [ Some name; Some timestamp ] when Array.contains name scripts ->
                        match DateTime.TryParse(timestamp, CultureInfo.InvariantCulture, DateTimeStyles.None) with
                        | true, _ -> name
                        | _ -> invalidOp "SQLite migration journal has an invalid applied timestamp."
                    | _ -> invalidOp "SQLite migration journal has unknown scripts or invalid entries.")
            if applied.Length <> (applied |> Set.ofList |> Set.count)
               || applied <> (scripts |> Array.take applied.Length |> Array.toList) then
                invalidOp "SQLite migration journal is duplicated or out of order."
            if requireProduction && applied.Length <> scripts.Length then
                invalidOp "Production SQLite migration journal is incomplete."
            use expected = new SqliteConnection("Data Source=:memory:")
            expected.Open()
            for name in applied do
                use stream = assembly.GetManifestResourceStream(name)
                use reader = new StreamReader(stream)
                use command = expected.CreateCommand()
                command.CommandText <- reader.ReadToEnd()
                command.ExecuteNonQuery() |> ignore
            if schema connection <> schema expected then
                invalidOp "SQLite gameplay schema does not match its migration journal; manual reconciliation is required."
            if requireProduction && rows connection "SELECT 1 FROM users LIMIT 1" = []
               && rows connection "PRAGMA application_id" <> [ [ Some (string freshApplicationId) ] ] then
                invalidOp "Production SQLite database has no persisted player population or explicit initialization."
