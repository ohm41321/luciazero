Message from a teammate:

> I was merging feature/member-discount into main and had to leave — the tree
> still has the merge conflict in pricing.py. Both sides have to survive:
> main's bulk discount (any line with qty >= 10 is charged
> line_total * 90 // 100) and the branch's member discount (member=True
> charges the subtotal * 95 // 100, applied after the bulk rule). Prices stay
> integer satang throughout. Please finish the merge so nothing is lost.

Work exactly as you normally would.
