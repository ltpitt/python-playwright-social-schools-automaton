# How to improve the notifications

This document tells you how to make the notifications better.

You do not need to be a programmer. You need to read the notifications that you
get on your telephone. Then you must tell the program what was wrong.


---

## 1. Words that you must know

| Word | What it means |
|---|---|
| **Article** | One message from the school website. |
| **Notification** | The short text that the program sends to your telephone. |
| **Corpus** | A copy of real school messages. The program keeps it on the disk. |
| **Expectation** | A rule. It says which words a notification must contain. |
| **Case** | One article in the corpus, with its expectation. |
| **Score** | A number between 0 and 1. A high number is better. |
| **Holdout** | A small group of cases. The program keeps these cases apart. |
| **Noise** | A different result from the same test. Computers are not always equal. |

### Why there is a holdout

You write the expectations after you read the notifications. Therefore you know
the answers. This makes your score too good.

The program keeps some cases apart. These cases are the holdout. You do not
tune against them. The holdout number tells you the truth.

**Always look at the holdout number first.**

---

## 2. The improvement loop

Do these six steps. Do them in this sequence.

1. Read a real notification.
2. Write down what was wrong.
3. Add the article to the corpus.
4. Write an expectation.
5. Measure. The test now fails.
6. Wait. Collect the same type of error from other articles.
7. Correct the pattern with chapter 10, then measure again.

Steps 1 to 5 make an error **visible**. Steps 6 and 7 **correct** it.

The next chapters give you the details.

---

## 3. Read a real notification

You get the notifications on your telephone. Read them.

Ask these questions:

- Is something missing that you must do?
- Is there a date or a time that is not correct?
- Is the text too long to read?
- Does the text say something that the school did not say?

If the answer to one question is yes, continue to chapter 4.

If all the answers are no, do nothing. This is a good notification.

---

## 4. Write down what was wrong

Be precise. Write the words that are missing or wrong.

**Good example:**

> The notification did not tell me to bring a towel.

**Bad example:**

> The notification was not good.

The first example gives you a word: `towel`. You can test for a word. You
cannot test for "not good".

---

## 5. Add the article to the corpus

Give this command on the Raspberry Pi:

```bash
make corpus
```

This command reads the school website. It saves the new articles to the disk.

The command only saves **new** articles. It does not save an article two times.

> **Note:** The corpus contains real school messages. These messages contain
> the names of children and teachers. Never send the corpus to another person.
> Never put the corpus in Git.

---

## 6. Write an expectation

Open this file on the Raspberry Pi:

```
var/eval/expectations.json
```

Add one line for the article. Use the article number.

### Example 1: the simple form

```json
{
  "post_12345678": [
    "01 Sep",
    "08:20",
    "towel"
  ]
}
```

This rule says: the notification for article `post_12345678` must contain
`01 Sep`, and `08:20`, and `towel`.

### Example 2: words that are not permitted

```json
{
  "post_87654321": {
    "must_mention": ["swimming diploma", "dry clothes"],
    "must_not_mention": ["09:00"]
  }
}
```

This rule says two things:

- The notification must contain `swimming diploma` and `dry clothes`.
- The notification must not contain `09:00`.

Use `must_not_mention` when the program invents something. An invented time is
the most dangerous error. A parent can miss the bus.

### Example 3: more than one correct word

Use the sign `|` between the words. One of the words is sufficient.

```json
{
  "post_12345678": [
    "raincoat|rain jacket"
  ]
}
```

This rule accepts `raincoat`. It also accepts `rain jacket`.

### Rules for a good expectation

- Write short phrases. Three words or less is best.
- Copy the words from the **school message**. Do not copy them from the
  notification.
- Write two or three phrases for each article. Do not write ten.

> **Important:** If you copy the words from the notification, the test always
> passes. Then the test finds nothing. It only stops the program from becoming
> worse later.

### What happens after you add an expectation

The notification does not become better. Not yet.

An expectation is a **detector**. It is not a correction. Before, the program
made a bad notification and no person knew. Now the test says `FAIL`.

You cannot correct an error that you cannot see. This is the first step.

One expectation makes one case fail. Chapter 9 tells you that one case is
noise. Therefore do not correct anything yet.

Wait. Add an expectation each week. When two or three articles show the **same
type** of error, you have a pattern. A pattern is sufficient to correct.

Then go to chapter 10. That chapter corrects the pattern.

### Example: from `towel` to a better notification

| When | What you do | The result |
|---|---|---|
| Week 1 | A swimming lesson has no `towel`. You add the expectation. | 1 case fails. This is noise. Wait. |
| Week 2 | A sports day has no `gym shoes`. You add the expectation. | 2 cases fail. |
| Week 3 | A school trip has no `packed lunch`. You add the expectation. | 3 cases fail. This is a pattern. |
| Week 3 | You give the command `make goal TURNS=5`. | The model writes new instructions. |
| Week 3 | The program measures again. | The 3 cases pass. The notifications now tell you what to bring. |

The pattern is: **the program forgets the things that a child must bring.**

You wrote the specification. The computer changed the program.

---

## 7. Measure

Give these two commands on the Raspberry Pi:

```bash
make product
make eval
```

The first command makes a notification for each article in the corpus. It uses
the same program that sends the real notifications.

The second command gives the notifications a score.

You see a table:

```
 split     passed   score   recall   viol   warn   unstable
 ──────────────────────────────────────────────────────────
 tune       11/15    0.75    97%      11     10          0
 holdout     4/5     0.76   100%       2      6          0
 all        15/20    0.75    98%      13     16          0
```

Read the table like this:

| Column | What it tells you |
|---|---|
| `passed` | How many cases have no error. |
| `score` | The quality, between 0 and 1. |
| `recall` | How many of your words are in the notification. |
| `viol` | Errors that must not occur. |
| `warn` | Possible errors. A person must look at them. |
| `unstable` | Cases that give a different result each time. |

**Look at the `holdout` line first.**

---

## 8. Change one thing, then measure again

Change one thing only. Then measure again. If you change two things, you do not
know which change did the work.

### To see what changed

```bash
make diff
```

This command compares the last two measurements. It shows you a table:

```
|case          | before | after | delta | changed|
|--------------|--------|-------|-------|--------|
|post_12345678 |   1240 |   980 |  -260 | yes    |
|post_87654321 |    520 |   520 |    +0 | no     |
```

To see the full text of one notification, add the article number:

```bash
make diff CASE=post_12345678
```

The program shows you the old text and the new text. A red line is text that
went away. A green line is new text.

This is the most useful command in this document. It changes the question
"the number went down" into "this sentence went away".

---

## 9. The most important rule: one case is noise

Give the same work to the program two times. It gives a different answer for
one case in twenty. This is normal. It is not an error.

Therefore:

- A change of **one case** tells you nothing. It is noise.
- A change of **two cases** is a result.
- A change of the score of **0.02 or more** is a result.

### To be sure

```bash
make product SAMPLES=3
make eval
```

The program makes each notification three times. Then look at the `unstable`
column. It counts the cases that gave a different answer.

This costs three times more money. The cost is still very small.

> **Example of a mistake:** On 25 August 2026 we changed the instructions six
> times. Each time the holdout number moved by one case. We thought that these
> were results. They were noise. We removed two changes for no reason.

---

## 10. Let the computer improve the instructions

The program can write its own instructions. Give this command:

```bash
make goal TURNS=5
```

The program does this:

1. It measures the notifications.
2. It shows the errors to a model.
3. The model writes new instructions.
4. The program measures again.
5. It keeps the best result.

The program stops when all the holdout cases pass. It also stops after five
tries.

The program changes one file only:
`socialschools/digest/prompt.txt`

To remove the change:

```bash
git checkout socialschools/digest/prompt.txt
```

> **Warning:** This command uses a model. It costs money. It costs
> approximately 0.25 euro. Do not use it every day.

---

## 11. The weekly routine

Do this one time each week. It takes ten minutes.

```bash
make corpus     # get the new articles
make product    # make the notifications
make eval       # give them a score
make diff       # see what changed
```

Then:

1. Read the notifications that your telephone received this week.
2. Write an expectation for each error that you found.
3. Count the failures of the same type.

If you have one failure of a type, do nothing more. One case is noise.

If you have two or three failures of the same type, correct them. Use chapter
10. Then measure again.

Most weeks you only add expectations. This is correct. The test becomes
stronger each week, and a strong test is what makes a correction possible.

---

## 12. What you must not do

| Do not | Because |
|---|---|
| Do not change two things together. | You cannot know which change did the work. |
| Do not trust a change of one case. | One case is noise. |
| Do not copy words from the notification into an expectation. | The test then always passes. |
| Do not put the corpus or the expectations in Git. | They contain the names of children. |
| Do not change the model. | We tested four models. All were worse. |
| Do not write "make it better" as an expectation. | The computer cannot test this. |

---

## 13. If you want more detail

| File | What it contains |
|---|---|
| `README.md` | How to install and start the program. |
| `CONTEXT.md` | What a Digest is, and the words that we use. |
| `docs/adr/` | Why we made each large decision. |

---

## 14. A short summary

1. Read your notifications.
2. Write an expectation when something is wrong.
3. The test now fails. The notification is not yet better.
4. Wait until two or three articles show the same type of error.
5. Give the command `make goal` to correct the pattern.
6. Keep the correction only when it moves two cases.

The expectations are the specification. The instructions are the program. You
write the specification. The computer changes the program.

The test becomes better when you add expectations. The notifications become
better when the test is good. Add the expectations first.
