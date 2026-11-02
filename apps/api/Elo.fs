namespace RNGWars

open System

module Elo =

    let calculate (playerElo: int) (opponentElo: int) (won: bool) (kFactor: int) : int =
        let playerF = float playerElo
        let opponentF = float opponentElo
        let ratingDiff = opponentF - playerF
        let expectedScore = 1.0 / (1.0 + Math.Pow(10.0, ratingDiff / 400.0))
        let actualScore = if won then 1.0 else 0.0
        let change = float kFactor * (actualScore - expectedScore)
        let newRating = playerF + change
        newRating |> int |> max 100 |> min 3000

    let calculateMultiplayer (playerElo: int) (opponentElo: int) (won: bool) : int =
        calculate playerElo opponentElo won 32

    let calculateForfeit (playerElo: int) (opponentElo: int) (won: bool) : int =
        calculate playerElo opponentElo won 16
