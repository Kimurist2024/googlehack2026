def is_palindrome(s):
    # ストリームを分割して、逆順に結合
    reversed_stream = s[::-1]
    
    # 分割されたストリームと元のストリームを比較
    return s == reversed_stream

# テスト
text = "A man, a plan, a canal: Panama"
result = is_palindrome(text)
print(f"'{text}' 是回文吗? {result}")
