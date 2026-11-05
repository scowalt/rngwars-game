const clients = [];
const sockets = [];
const pause = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const require = (condition, message) => {
  if (!condition) throw new Error(message);
};
const deferred = () => {
  let resolve;
  const promise = new Promise((done) => {
    resolve = done;
  });
  return { promise, resolve };
};

async function request(path, token, body) {
  const response = await fetch("http://127.0.0.1:5000" + path, {
    method: body === undefined ? "GET" : "POST",
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: "Bearer " + token } : {}),
    },
    body: body === undefined ? undefined : JSON.stringify(body),
    signal: AbortSignal.timeout(5000),
  });
  require(response.ok, "multiplayer_HTTP_failed");
  return response.json();
}

async function connect(identity) {
  const ready = deferred();
  const found = deferred();
  const completed = deferred();
  const pending = new Map();
  const phases = [];
  const socket = new WebSocket(
    "ws://127.0.0.1:5000/hubs/game?access_token=" + encodeURIComponent(identity.token)
  );
  sockets.push(socket);
  let next = 0;
  const send = (message) => socket.send(JSON.stringify(message) + "\u001e");
  const client = {
    identity,
    ready,
    found,
    completed,
    phases,
    errors: [],
    invoke(target, args = []) {
      const id = String(++next);
      const completion = deferred();
      pending.set(id, completion);
      send({ type: 1, invocationId: id, target, arguments: args });
      return completion.promise;
    },
  };
  socket.onopen = () => send({ protocol: "json", version: 1 });
  socket.onerror = () => client.errors.push("socket_error");
  socket.onmessage = ({ data }) => {
    for (const raw of String(data).split("\u001e").filter(Boolean)) {
      const message = JSON.parse(raw);
      if (Object.keys(message).length === 0) ready.resolve();
      if (message.type === 3) {
        if (message.error) client.errors.push("invocation_error");
        pending.get(message.invocationId)?.resolve();
      }
      if (message.type === 1) {
        const event = message.arguments[0];
        if (message.target === "MatchFound") found.resolve(event.matchId);
        if (message.target === "PhaseChanged") phases.push(event.phase);
        if (message.target === "MatchCompleted") completed.resolve(event);
        if (message.target === "MatchCancelled") client.errors.push("match_cancelled");
      }
    }
  };
  await ready.promise;
  return client;
}

async function exercise() {
  for (let index = 0; index < 2; index++) {
    const identity = await request("/api/users/anonymous", undefined, {});
    require(identity.user.rngScore === 1200, "unexpected_initial_rating");
    clients.push(await connect(identity));
  }
  await clients[0].invoke("JoinQueue");
  await clients[1].invoke("JoinQueue");
  const matches = await Promise.all(clients.map((client) => client.found.promise));
  require(matches[0] === matches[1], "different_matches");
  await clients[0].invoke("JoinMatch", [matches[0]]);
  await pause(100);
  require(clients.every((client) => client.phases.length === 0), "started_without_both_players");
  await clients[1].invoke("JoinMatch", [matches[1]]);
  const completions = await Promise.all(clients.map((client) => client.completed.promise));
  require(clients.every(
    (client) =>
      client.errors.length === 0 &&
      client.phases.join(",") === "countdown,countdown,countdown,rolling,revealed"
  ), "invalid_multiplayer_progression");
  require(completions[0].winnerId === completions[1].winnerId, "inconsistent_winner");
  const profiles = await Promise.all(
    clients.map((client) => request("/api/users/me", client.identity.token))
  );
  require(profiles
    .map((profile) => profile.rngScore)
    .sort((a, b) => a - b)
    .join(",") === "1184,1216", "ratings_not_persisted");
  const histories = await Promise.all(
    clients.map((client) => request("/api/users/me/matches", client.identity.token))
  );
  require(histories.every((history) =>
    JSON.stringify(history).includes(matches[0])
  ), "match_history_missing");
  console.log(
    JSON.stringify({
      multiplayer_sequential_join_completion: true,
      both_clients_observed_all_phases: true,
      ratings_and_history_persisted: true,
    })
  );
}

let timer;
try {
  await Promise.race([
    exercise(),
    new Promise((_, reject) => {
      timer = setTimeout(() => reject(new Error("multiplayer_completion_deadline")), 20000);
    }),
  ]);
} catch (error) {
  console.error("Native multiplayer validation failed: " + error.message);
  process.exitCode = 1;
} finally {
  clearTimeout(timer);
  for (const socket of sockets) socket.close();
}
