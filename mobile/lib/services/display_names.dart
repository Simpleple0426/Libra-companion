class DisplayNames {
  const DisplayNames._();

  static String libra = '左然';
  static String user = '我';
  static String companionText(String text) {
    final name = user.trim().isEmpty ? '我' : user.trim();
    return text.replaceAll('陪伴用户', '陪伴$name').replaceAll('陪用户', '陪$name');
  }

  static String? libraAvatarPath;
  static String? userAvatarPath;
}
