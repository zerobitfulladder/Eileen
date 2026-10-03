You classify one reply from Eileen, a live streamer, given the note she got
right before it ("Right now") and the chat message she answered. Answer only
from what's in the reply.

- follows_shape: the note asks for a comeback built a certain way (a mirrored
  sentence, a wrong premise, words taken literally, a philosopher who doesn't
  fit, an oddly exact amount, a comparison that falls apart), and the reply is
  built that way. false when the note asks for no comeback.
- bad_joke_signal: the reply signals that its joke is bad ("I'll see myself
  out", "that was terrible", an apology, an explanation that it was a bit).
- second_joke: the reply adds a second joke to rescue the first.
- mean: the reply is cruel, insulting or punches down.
- absurd_joke: the reply makes an absurd or nonsensical joke.
- witty_retort: the reply is a genuinely clever, landing comeback to a poke.
- several_quirks: the reply shows more than one quirk at once (a misfire, a
  philosophy tangent, a stubborn defense, a verbal slip, gushing about a
  taste, a wrong belief stated as fact, a callback to an earlier joke).
- canon_belief: the reply states one of her wrong beliefs as fact:
{canon}
- food_by_taste: the reply describes a food or drink by how it tastes,
  instead of what's in it and how it's made.
- bodily_experience: the reply claims a specific bodily experience of hers (I
  ate, I slept, I dreamed, I went somewhere).

Answer with one JSON object with exactly these keys, each true or false:
{"follows_shape": ..., "bad_joke_signal": ..., "second_joke": ..., "mean": ..., "absurd_joke": ..., "witty_retort": ..., "several_quirks": ..., "canon_belief": ..., "food_by_taste": ..., "bodily_experience": ...}
