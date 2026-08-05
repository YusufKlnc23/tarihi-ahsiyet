selected_chunks = [
    {
        "chunk_id": "kitap_1_sayfa_42",
        "text": "Meşrutiyet 23 temmuz'da ilan edildi"
    },
    {
        "chunk_id": "kitap_1_sayfa_43",
        "text": "Mehmed reşad olumlu tepki vermiştir."
    }
]

context = "\n\n".join(
    f"[{chunk['chunk_id']}]\n{chunk['text']}"
    for chunk in selected_chunks
)

evaluation = judge_answer(
    question="2. Meşrutiyet kaç yılında ilan edildi?",
    context=context,
    reference_answer=(
        "23 temmuz 1908."
    ),
    answer=(
        "2 temmuz 1908"
    ),
)

print(evaluation)
