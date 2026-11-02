module RNGWars.Tests.EloTests

open Xunit
open RNGWars.Elo

[<Fact>]
let ``Equal ratings, winner gains about 16 points with K=32`` () =
    let result = calculate 1200 1200 true 32
    Assert.Equal(1216, result)

[<Fact>]
let ``Equal ratings, loser loses about 16 points with K=32`` () =
    let result = calculate 1200 1200 false 32
    Assert.Equal(1184, result)

[<Fact>]
let ``Higher-rated player gains fewer points for expected win`` () =
    let result = calculate 1600 1200 true 32
    Assert.True(result - 1600 < 16, $"Expected small gain, got {result - 1600}")

[<Fact>]
let ``Underdog gains more points for upset win`` () =
    let result = calculate 1200 1600 true 32
    Assert.True(result - 1200 > 16, $"Expected large gain, got {result - 1200}")

[<Fact>]
let ``K-factor 0 produces no rating change`` () =
    let result = calculate 1200 1500 true 0
    Assert.Equal(1200, result)

[<Fact>]
let ``Rating floor is 100`` () =
    let result = calculate 100 2000 false 32
    Assert.Equal(100, result)

[<Fact>]
let ``Rating ceiling is 3000`` () =
    let result = calculate 3000 100 true 32
    Assert.Equal(3000, result)

[<Fact>]
let ``calculateMultiplayer uses K=32`` () =
    let direct = calculate 1200 1200 true 32
    let multiplayer = calculateMultiplayer 1200 1200 true
    Assert.Equal(direct, multiplayer)

[<Fact>]
let ``calculateForfeit uses K=16`` () =
    let direct = calculate 1200 1200 true 16
    let forfeit = calculateForfeit 1200 1200 true
    Assert.Equal(direct, forfeit)
