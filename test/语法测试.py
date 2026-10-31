obj = {
    "name":"yangmi",
    "eat":lambda x:x*2
}
print(obj["eat"](10))

def create_multipliers():
    return [lambda x: i * x for i in range(3)]

def create_multiplier(x)
    nonlocal x
    def inner():
        for i in range(3):
            result = i * x
        return result
    return inner()


multipliers = create_multipliers()
print([m(2) for m in multipliers])

create_multiplier(2)
print(create_multiplier(2))