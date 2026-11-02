namespace RNGWars.Api.Tests

open System.Net
open System.Net.Http
open System.Text.Json
open Xunit

module ApiHttpTests =
    let private json (response: HttpResponseMessage) = task {
        let! text = response.Content.ReadAsStringAsync()
        return JsonDocument.Parse(text)
    }

    [<Fact>]
    let ``local signup profile update and restart preserve the anonymous identity`` () = task {
        use api = new ApiHttpFixture()
        let! ready = api.Start()
        Assert.True(ready, "Isolated API failed startup (logs withheld).")
        use! signup = api.Request(HttpMethod.Post, "/api/users/anonymous")
        Assert.Equal(HttpStatusCode.Created, signup.StatusCode)
        use! created = json signup
        let token = created.RootElement.GetProperty("token").GetString()
        let id = created.RootElement.GetProperty("user").GetProperty("id").GetString()
        Assert.False(System.String.IsNullOrWhiteSpace(token), "Signup must issue a usable token.")
        use! profile = api.Request(HttpMethod.Get, "/api/users/me", token = token)
        Assert.Equal(HttpStatusCode.OK, profile.StatusCode)
        use! user = json profile
        Assert.Equal(id, user.RootElement.GetProperty("id").GetString())
        use! saved = api.Request(HttpMethod.Put, "/api/users/me", token = token, body = "{\"username\":\"HttpTracer\"}")
        Assert.Equal(HttpStatusCode.OK, saved.StatusCode)
        use! updated = api.Request(HttpMethod.Get, "/api/users/me", token = token)
        Assert.Equal(HttpStatusCode.OK, updated.StatusCode)
        use! changed = json updated
        Assert.Equal("HttpTracer", changed.RootElement.GetProperty("username").GetString())
        use! practice = api.Request(HttpMethod.Post, "/api/matches/practice", token = token)
        Assert.Equal(HttpStatusCode.Created, practice.StatusCode)
        use! started = json practice
        let matchId = started.RootElement.GetProperty("matchId").GetString()
        use! matchResponse = api.Request(HttpMethod.Get, "/api/matches/" + matchId, token = token)
        Assert.Equal(HttpStatusCode.OK, matchResponse.StatusCode)
        use! matchBefore = json matchResponse
        Assert.Equal(matchId, matchBefore.RootElement.GetProperty("id").GetString())
        let matchJson = matchBefore.RootElement.GetRawText()
        api.Stop()
        let! restarted = api.Start()
        Assert.True(restarted, "Repeat startup must preserve migrations and player identity.")
        use! returning = api.Request(HttpMethod.Get, "/api/users/me", token = token)
        Assert.Equal(HttpStatusCode.OK, returning.StatusCode)
        use! persisted = json returning
        Assert.Equal(id, persisted.RootElement.GetProperty("id").GetString())
        Assert.Equal("HttpTracer", persisted.RootElement.GetProperty("username").GetString())
        use! savedMatch = api.Request(HttpMethod.Get, "/api/matches/" + matchId, token = token)
        Assert.Equal(HttpStatusCode.OK, savedMatch.StatusCode)
        use! matchAfter = json savedMatch
        Assert.Equal(matchJson, matchAfter.RootElement.GetRawText())
    }

    [<Fact>]
    let ``imported production identity completed history and leaderboard survive HTTP restart`` () = task {
        use api = new ApiHttpFixture(configuration = [ "ASPNETCORE_ENVIRONMENT", "Production" ])
        SyntheticDatabase.seedImported api.DatabasePath
        let before = SyntheticDatabase.snapshot api.DatabasePath
        let! ready = api.Start()
        Assert.True(ready, "A valid transferred database must serve production HTTP.")
        Assert.Equal<string list>(before, SyntheticDatabase.snapshot api.DatabasePath)
        use! profile = api.Request(HttpMethod.Get, "/api/users/me", token = "11111111-1111-4111-8111-111111111111")
        Assert.Equal(HttpStatusCode.OK, profile.StatusCode)
        use! player = json profile
        Assert.Equal("synthetic-player-1", player.RootElement.GetProperty("id").GetString())
        Assert.Equal(1456, player.RootElement.GetProperty("rngScore").GetInt32())
        use! history = api.Request(HttpMethod.Get, "/api/users/me/matches", token = "11111111-1111-4111-8111-111111111111")
        Assert.Equal(HttpStatusCode.OK, history.StatusCode)
        use! matches = json history
        Assert.Equal(2, matches.RootElement.GetProperty("matches").GetArrayLength())
        Assert.Equal("synthetic-practice-match", matches.RootElement.GetProperty("matches").[0].GetProperty("id").GetString())
        let historyJson = matches.RootElement.GetRawText()
        use! leaderboard = api.Request(HttpMethod.Get, "/api/leaderboard")
        Assert.Equal(HttpStatusCode.OK, leaderboard.StatusCode)
        use! rankings = json leaderboard
        Assert.Equal("synthetic-player-1", rankings.RootElement.GetProperty("entries").[0].GetProperty("userId").GetString())
        Assert.Equal(12, rankings.RootElement.GetProperty("entries").[0].GetProperty("totalWins").GetInt32())
        let leaderboardJson = rankings.RootElement.GetRawText()
        let beforeRestart = SyntheticDatabase.snapshot api.DatabasePath
        api.Stop()
        let! restarted = api.Start()
        Assert.True(restarted, "Production restart must preserve completed results.")
        Assert.Equal<string list>(beforeRestart, SyntheticDatabase.snapshot api.DatabasePath)
        use! returning = api.Request(HttpMethod.Get, "/api/users/me", token = "11111111-1111-4111-8111-111111111111")
        Assert.Equal(HttpStatusCode.OK, returning.StatusCode)
        use! persisted = json returning
        Assert.Equal(player.RootElement.GetRawText(), persisted.RootElement.GetRawText())
        use! repeated = api.Request(HttpMethod.Get, "/api/users/me/matches", token = "11111111-1111-4111-8111-111111111111")
        Assert.Equal(HttpStatusCode.OK, repeated.StatusCode)
        use! persistedMatches = json repeated
        Assert.Equal(historyJson, persistedMatches.RootElement.GetRawText())
        use! repeatedRankings = api.Request(HttpMethod.Get, "/api/leaderboard")
        Assert.Equal(HttpStatusCode.OK, repeatedRankings.StatusCode)
        use! persistedRankings = json repeatedRankings
        Assert.Equal(leaderboardJson, persistedRankings.RootElement.GetRawText())
    }

    [<Fact>]
    let ``production HTTP startup rejects a missing expected database without serving a fresh population`` () = task {
        use api = new ApiHttpFixture(configuration = [ "ASPNETCORE_ENVIRONMENT", "Production" ])
        let! ready = api.Start()
        Assert.False(ready, "Missing production storage must prevent serving HTTP.")
        Assert.True(api.LastExitCode |> Option.exists ((<>) 0))
        Assert.Contains("SQLite Error 14", api.Logs)
        Assert.False(api.LocalDatabaseExists)
    }
