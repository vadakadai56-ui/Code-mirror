"""Built-in example programs shown in the "Examples" menu.

Each example is small on purpose: the tracer stops after 500 steps, and a
short program is easier to follow one step at a time.
"""

EXAMPLES = [
    {
        "id": "fibonacci",
        "title": "Fibonacci (while loop)",
        "code": '''def fibonacci(n):
    a, b = 0, 1
    count = 0
    while count < n:
        a, b = b, a + b
        count += 1
    return a

result = fibonacci(8)
print("fibonacci(8) =", result)
''',
    },
    {
        "id": "bubble_sort",
        "title": "Bubble sort (nested for loops)",
        "code": '''def bubble_sort(items):
    n = len(items)
    for i in range(n):
        swapped = False
        for j in range(n - 1 - i):
            if items[j] > items[j + 1]:
                items[j], items[j + 1] = items[j + 1], items[j]
                swapped = True
        if not swapped:
            break
    return items

numbers = [5, 2, 9, 1, 6]
print(bubble_sort(numbers))
''',
    },
    {
        "id": "factorial",
        "title": "Factorial (recursion)",
        "code": '''def factorial(n):
    if n <= 1:
        return 1
    return n * factorial(n - 1)

answer = factorial(5)
print("5! =", answer)
''',
    },
    {
        "id": "fizzbuzz",
        "title": "FizzBuzz (if / elif / else)",
        "code": '''for n in range(1, 16):
    if n % 15 == 0:
        print("FizzBuzz")
    elif n % 3 == 0:
        print("Fizz")
    elif n % 5 == 0:
        print("Buzz")
    else:
        print(n)
''',
    },
]
