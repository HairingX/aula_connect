# The shapes of Aula's answers

`src/aula_connect/shapes.json` holds the shape of each answer Aula was seen to send: for each
request, the verb and what was asked for, such as `GET calendar.getEventById`, the type at each
place of the answer, such as `data.description.html: ["str"]` or `data.lesson: ["null", "object"]`.
It holds the names Aula gives its fields and their types, never a value, so it tells nothing of
anyone; and it is the reference for what Aula sends when the answers are not at hand, or Aula
changes them.

- **Where it comes from.** The diagnostics of the Home Assistant integration list the answers
  Aula gave, with who someone is replaced. Their shapes are added with
  `python scripts/update_shapes.py <diagnostics>.json...`; the diagnostics themselves stay on the
  machine they were downloaded to. A shape only grows: a field Aula sent once stays.
- **What it is checked against.** The client compares each answer to it, and names a field
  new to an object it knows, or a type other than null a field has not had, as an anomaly of the
  kind `unknown_shape`, such as `GET calendar.getEventById: data.newField (str)`. What lies under
  a field seen only as null is not known yet, and names nothing.
- **What the tests hold to it.** The simulated Aula of `aula_connect.testing` answers every
  request the reference knows, in no shape the reference does not know, so that the made-up
  answers the tests run on are shaped as Aula's.
