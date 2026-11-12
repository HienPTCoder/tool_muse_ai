"""Thư viện chủ đề cho "Tạo hàng loạt video tạo dáng": mỗi chủ đề = 1 bối cảnh + trang phục nữ/nam hợp cảnh + gợi ý pose.
plan(n, …) bốc n chủ đề khác nhau (ưu tiên chủ đề chưa dùng ở các lô trước) và ghép với n người mẫu khác nhau
(nét người, gu, tóc, dáng người đều khác nhau) -> mỗi video 1 người mẫu, 1 bối cảnh, 1 bộ pose riêng."""

import random

# (tên bối cảnh, mô tả bối cảnh, phong cách trang phục, gu hợp cảnh, trang phục nữ, pose nữ, trang phục nam, pose nam)
THEMES = [
    ("Rooftop Seoul lúc hoàng hôn xanh",
     "Sân thượng toà nhà cao tầng ở Seoul lúc blue hour: lan can kính, ghế dài gỗ, bồn cây xanh, sàn gỗ, toà nhà sáng đèn và tháp Namsan mờ xa, đèn dây vàng ấm.",
     "Rooftop thành phố", ["Hàn Quốc", "Clean girl"],
     "đầm lụa slip dress hai dây ôm dáng, blazer khoác hờ vai, khuyên bạc nhỏ",
     "tựa lan can kính, ngồi ghế dài vắt chân, vén tóc trong gió, xoay lưng khoe vai trần ngoái lại",
     "sơ mi lụa đen mở 3 cúc, quần âu ống rộng, dây chuyền bạc",
     "tựa lan can kính đút tay túi, ngồi ghế dài gác tay lên lưng ghế, vuốt tóc nhìn xa, ngoái nhìn qua vai"),
    ("Bãi biển nhiệt đới nắng chiều",
     "Bãi cát trắng mịn lúc nắng chiều vàng: sóng trắng nhỏ, vài tảng đá đen, cột gỗ lối xuống biển, chòi lá, cây dừa nghiêng, trời xanh trong.",
     "Đi biển", ["Boho", "Nàng thơ"],
     "bikini đan móc + chân váy lụa xẻ cao, sơ mi linen trắng khoác mở, mũ cói",
     "ngồi trên tảng đá, đi chân trần trên cát giữ mũ, tựa cột gỗ, nghiêng người vén váy trong gió",
     "sơ mi linen trắng mở hết cúc lộ cơ bụng, quần short linen be, vòng tay gỗ",
     "đứng chân rộng giữa sóng vén áo, ngồi trên tảng đá chống tay ngả người, đi trên cát cầm áo vắt vai, vuốt tóc ướt"),
    ("Hẻm phố đêm neon sau mưa",
     "Con hẻm phố đêm châu Á sau mưa: biển hiệu neon hồng xanh (không chữ đọc được), cửa hàng tiện lợi sáng đèn, cầu thang sắt, mặt đường ướt phản chiếu neon, máy bán hàng tự động.",
     "Đường phố", ["Streetwear", "Y2K"],
     "crop top ôm + váy da mini, boots cao cổ, áo khoác bomber trễ vai",
     "ngồi xổm street style trước máy bán hàng, tựa tường neon kéo kính râm, ngồi bậc cầu thang chéo chân dài, ngoái lại dưới ánh neon",
     "sơ mi lụa đen mở gần hết cúc, quần âu ống rộng, dây chuyền bạc, tóc rủ có texture",
     "tựa tường neon đút tay túi, ngồi bậc cầu thang chống khuỷu tay lên gối, vuốt tóc ngửa mặt, ngoái nhìn qua vai"),
    ("Hồ bơi biệt thự trắng Santorini",
     "Hồ bơi vô cực của biệt thự trắng ở Santorini: tường vôi trắng bo tròn, mái vòm xanh dương, ghế tắm nắng, hoa giấy hồng, nước xanh ngọc, biển Aegean phía xa, nắng chiều vàng.",
     "Hồ bơi / resort", ["Âu Mỹ", "Old money"],
     "đồ bơi một mảnh cut-out trắng ngà + kimono voan mỏng, kính râm, vòng vàng",
     "ngồi mép hồ chân thả xuống nước, nằm nghiêng trên ghế tắm nắng, tựa tường trắng vuốt tóc ướt",
     "quần bơi ngắn màu kem, sơ mi linen trắng mở, kính râm gọng vàng, dây chuyền vàng",
     "ngồi mép hồ chống tay ngả người, đứng tựa tường trắng khoanh tay, bước ra từ hồ vuốt tóc ướt"),
    ("Bến du thuyền sang trọng",
     "Bến du thuyền: cầu tàu gỗ teak, du thuyền trắng neo đậu, cọc buộc dây, dây thừng cuộn, biển xanh lấp lánh, dãy nhà màu kem trên đồi xa, nắng chiều.",
     "Du lịch", ["Old money", "Âu Mỹ"],
     "đầm linen trắng hở lưng, khăn lụa buộc tóc, kính râm mắt mèo, túi cói",
     "ngồi trên cọc buộc dây vắt chân, tựa lan can du thuyền gió thổi váy, đi trên cầu tàu giữ kính râm",
     "sơ mi linen trắng mở ngực, quần âu be, kính râm, đồng hồ cổ điển",
     "ngồi trên cọc buộc dây, tựa lan can du thuyền, đi trên cầu tàu cởi kính râm, xắn tay áo nhìn xa"),
    ("Phố mua sắm cao cấp",
     "Đại lộ mua sắm cao cấp: mặt tiền đá cẩm thạch, cửa kính trưng bày lớn (không chữ, không logo), cây ngô đồng, ghế đá, bậc thềm đá, đèn đường cổ điển, ánh chiều ấm.",
     "Mua sắm", ["Douyin / Trung Quốc", "Old money"],
     "áo corset satin + quần ống loe cạp cao, blazer vắt vai, túi hộp, khuyên ngọc trai",
     "ngồi bậc thềm đá vắt chân, tựa cửa kính cầm túi, bước catwalk vắt blazer, chạm khuyên tai nghiêng đầu",
     "suit be không cà vạt, sơ mi trắng mở cổ, giày lười da, túi tote da",
     "tựa cửa kính chỉnh cổ tay áo, ngồi bậc thềm hai tay đan gối, bước catwalk vắt áo vest, cầm túi nhìn ngang"),
    ("Đồi cỏ lau lúc chiều",
     "Đồi cỏ lau hồng lúc nắng chiều xiên: cỏ lau cao ngang hông, lối mòn đất, gốc thông, hàng rào gỗ cũ, đồi thông xa mờ sương, nắng vàng ngược nhẹ.",
     "Picnic công viên", ["Nàng thơ", "Hàn Quốc"],
     "đầm lụa hở lưng màu kem dài qua gối xẻ đùi, áo len mỏng khoác vai",
     "ngồi trên hàng rào gỗ, đi giữa cỏ lau tay lướt bông lau, quay lưng khoe lưng trần ngoái lại, nằm nghiêng trên cỏ chống tay",
     "áo len dệt kim cổ chữ V không áo trong, quần kaki be, giày da",
     "ngồi trên hàng rào gỗ, đi giữa cỏ lau ngoái lại, nằm ngửa trên cỏ gác tay sau đầu, đứng vắt áo khoác qua vai"),
    ("Phố cổ tường vàng đèn lồng",
     "Phố cổ châu Á: tường vàng rêu phong, cửa gỗ nâu, đèn lồng lụa nhiều màu treo cao, hoa giấy hồng rủ xuống, xe đạp cũ dựng tường, bậc thềm đá, ánh chiều ấm.",
     "Vintage", ["Tối giản", "Nàng thơ"],
     "áo yếm lụa đỏ + chân váy lụa xẻ, khăn voan, hoa tai ngọc",
     "tựa tường vàng cầm đèn lồng, ngồi bậc thềm nghiêng đầu, dắt xe đạp ngoái lại, đứng dưới hoa giấy vén tóc",
     "áo polo len dệt kim mở cổ ôm dáng, quần âu cạp cao, giày lười da, đồng hồ dây da",
     "tựa tường vàng một chân gác tường, ngồi bậc thềm hai tay chống gối, dắt xe đạp ngoái lại, chỉnh cổ tay áo nhìn xuống"),
    ("Phố Shibuya về đêm",
     "Góc phố Tokyo về đêm: biển hiệu neon và màn hình sáng (không chữ đọc được), máy bán hàng tự động, lan can thép, cầu thang lên cầu vượt, vạch kẻ đường, mặt đường hơi ướt.",
     "Đường phố", ["Nhật Bản", "Y2K"],
     "áo khoác da cropped + váy xếp ly mini, tất đùi, boots đế dày",
     "nhảy nhẹ trên vạch kẻ đường, ngồi bậc cầu thang chéo chân dài, tựa lan can kéo kính râm, ngồi xổm trước máy bán hàng",
     "áo khoác da đen + áo ba lỗ trắng, quần cargo đen, boots",
     "tựa lan can kéo cổ áo khoác, đi trên vạch kẻ đường đút tay túi, ngồi bậc cầu thang chống tay, ngồi xổm street style"),
    ("Đồi cát sa mạc lúc hoàng hôn",
     "Đồi cát sa mạc lúc hoàng hôn: sóng cát mịn, bóng đổ dài, vài tảng đá đỏ, cây keo khô đơn độc, trời cam hồng chuyển tím.",
     "Du lịch", ["Âu Mỹ", "Tối giản"],
     "đầm voan đỏ dài bay trong gió xẻ cao, vòng vàng nhiều lớp, khăn voan",
     "đứng trên đỉnh đồi cát váy bay, ngồi trên cát chống tay ngả người, bước trên cát ngoái lại, quỳ một gối vuốt cát",
     "blazer kem mở hoàn toàn khoe cơ bụng, quần âu ống rộng màu cát, dây chuyền vàng",
     "đứng chân rộng mở blazer trong gió, ngồi trên tảng đá chống tay ngả người, bước trên đồi cát ngoái lại, quỳ một gối vuốt cát"),
    ("Villa giữa rừng nhiệt đới",
     "Hồ bơi vô cực của villa giữa rừng nhiệt đới buổi sáng: xích đu gỗ treo trên cây lớn, sàn gỗ teak, lá chuối và dương xỉ, ruộng bậc thang mờ sương xa, hoa sứ trắng, nắng xuyên tán lá.",
     "Hồ bơi / resort", ["Boho", "Nàng thơ"],
     "bikini tam giác màu kem + váy quấn sarong voan mỏng xẻ cao, vòng chân vỏ sò, hoa sứ cài tai",
     "ngồi xích đu vắt chân, ngồi mép hồ nghiêng người về sau chống tay, đứng dưới tán lá vuốt tóc, nằm sấp trên sàn gỗ chống cằm",
     "quần linen trắng xắn gấu, không áo khoe cơ bụng, vòng cổ gỗ, khăn tắm vắt vai",
     "ngồi xích đu chống tay, ngồi mép hồ chân thả nước, đứng dưới tán lá vuốt tóc ướt, tựa thân cây khoanh tay"),
    ("Phố Paris và ban công sắt",
     "Con phố Paris kiểu Haussmann buổi chiều: toà nhà đá vôi màu kem, ban công sắt uốn đen, quán cà phê vỉa hè ghế mây, chậu phong lữ đỏ, đường lát đá, tháp Eiffel mờ xa cuối phố.",
     "Dạo phố", ["Old money", "Âu Mỹ"],
     "đầm satin đen hai dây cổ đổ, trench coat be khoác vai, giày cao gót mũi nhọn, son đỏ",
     "ngồi ghế mây vắt chân cầm tách cà phê, tựa cột đèn ngoái nhìn, bước qua đường kéo vạt trench coat, tựa ban công sắt chống cằm",
     "áo len cổ lọ đen ôm, áo măng tô dạ xám, quần âu, kính râm",
     "ngồi ghế mây vắt chân cầm tách cà phê, tựa cột đèn đút tay túi áo, bước qua đường chỉnh cổ áo, tựa ban công nhìn xuống"),
    ("Sân thượng gạch đỏ New York",
     "Sân thượng toà nhà gạch đỏ ở Brooklyn lúc hoàng hôn: cầu thang thoát hiểm sắt đen, bồn nước gỗ trên mái, tường gạch, đường chân trời Manhattan và cầu phía xa, trời cam tím.",
     "Đường phố", ["Streetwear", "Âu Mỹ"],
     "áo hai dây ren đen + quần jean cạp cao, áo khoác da oversize trễ vai, boots",
     "ngồi bậc cầu thang sắt vắt chân, tựa tường gạch kéo áo khoác, ngồi mép mái nhìn xa, đứng vuốt tóc ngửa mặt",
     "áo ba lỗ trắng ôm sát lộ cơ tay, áo khoác da đen vắt vai, quần jean đen rách gối, dây chuyền bạc",
     "ngồi bậc cầu thang sắt chống khuỷu tay, tựa tường gạch kéo áo khoác qua vai, ngồi mép mái nhìn xa, đứng vuốt tóc ngửa mặt"),
    ("Cầu gỗ villa trên mặt nước",
     "Cầu gỗ dẫn ra các villa mái lá trên mặt nước: nước biển trong xanh ngọc thấy cát trắng bên dưới, bậc thang gỗ xuống biển, ghế lười, cột gỗ, mái tranh, trời xanh mây trắng.",
     "Đi biển", ["Âu Mỹ", "Clean girl"],
     "đồ bơi một mảnh khoét lưng sâu màu đỏ san hô, sơ mi lụa trắng khoác mở, kính râm gọng vàng, mũ rộng vành",
     "ngồi trên bậc thang gỗ chân chạm nước, đi trên cầu gỗ giữ mũ trong gió, nằm nghiêng trên ghế lười, tựa cột gỗ vén tóc",
     "quần bơi ngắn xanh navy, sơ mi lụa in họa tiết mở hết cúc, kính râm",
     "ngồi bậc thang gỗ chân chạm nước, đi trên cầu gỗ vắt áo, nằm trên ghế lười gác tay sau đầu, tựa cột gỗ nhìn biển"),
    ("Đồi nho Tuscany lúc hoàng hôn",
     "Vườn nho trên đồi Tuscany lúc hoàng hôn: hàng nho thẳng tắp, đường đất trắng, hàng cây bách, biệt thự đá mái ngói đỏ, thùng rượu gỗ, xe Vespa cổ màu kem, nắng vàng cam.",
     "Du lịch", ["Old money", "Tối giản"],
     "đầm hoa nhí hai dây dài xẻ tà, mũ rơm, giỏ mây",
     "ngồi trên thùng rượu gỗ vắt chân, tựa xe Vespa cầm mũ, đi giữa hàng nho tay lướt lá, đứng ngược nắng vén tóc",
     "sơ mi lụa màu kem mở 3 cúc, quần âu nâu cạp cao, thắt lưng da, kính râm đồi mồi",
     "ngồi trên thùng rượu chống tay lên gối, tựa xe Vespa khoanh tay, đi giữa hàng nho cởi kính râm, xắn tay áo nhìn hoàng hôn"),
    ("Khu nghỉ tuyết trên núi",
     "Khu nghỉ trên núi tuyết: chalet gỗ có cửa kính lớn, lò sưởi ngoài trời đang cháy, hàng thông phủ tuyết, núi tuyết trắng xa, trời xanh nắng sớm, tuyết mịn.",
     "Mùa đông tuyết", ["Old money", "Âu Mỹ"],
     "áo len trắng trễ vai dáng ngắn, quần legging da đen, boots lông, mũ len",
     "ngồi bên lò sưởi ngoài trời ôm gối, tựa cửa kính chalet, đi trên tuyết kéo cổ áo, ném tuyết cười",
     "áo len cổ lọ ôm sát, áo phao không tay, quần đen, kính trượt tuyết trên đầu",
     "ngồi bên lò sưởi chống tay lên gối, tựa cửa kính chalet khoanh tay, đi trên tuyết kéo khoá áo, vác ván trượt nhìn xa"),
    ("Quán bar rooftop đêm",
     "Quán bar rooftop sang trọng về đêm: quầy bar đá cẩm thạch, ghế nhung, bể bơi nhỏ phát sáng xanh, đèn dây ấm, toà nhà chọc trời sáng đèn phía xa.",
     "Dạ tiệc", ["Old money", "Douyin / Trung Quốc"],
     "đầm sequin ánh bạc ôm sát xẻ đùi, giày quai mảnh, hoa tai dài",
     "tựa quầy bar cầm ly rượu, ngồi ghế nhung vắt chân, đứng bên bể bơi phát sáng vén tóc, ngoái lại trên nền đèn thành phố",
     "suit đen không sơ mi trong, dây chuyền mảnh, đồng hồ, tóc vuốt ngược",
     "tựa quầy bar cầm ly, ngồi ghế nhung dang tay trên lưng ghế, đứng bên bể bơi chỉnh khuy áo, đút tay túi nhìn thành phố"),
    ("Cánh đồng hoa oải hương",
     "Cánh đồng hoa oải hương tím trải dài lúc hoàng hôn: luống hoa thẳng hàng, cây cổ thụ đơn độc, nhà đá nhỏ, ghế gỗ, trời hồng cam.",
     "Picnic công viên", ["Nàng thơ", "Boho"],
     "đầm voan trắng trễ vai dài bay, mũ cói rộng vành",
     "đi giữa luống hoa tay lướt hoa, ngồi trên ghế gỗ giữ mũ, đứng xoay váy, nằm giữa hoa nhìn trời",
     "sơ mi trắng xắn tay mở cổ, quần âu be, dây đeo quần, mũ panama",
     "đi giữa luống hoa tay đút túi, ngồi trên ghế gỗ vắt chân, đứng dưới cây cổ thụ cầm mũ, ngoái lại cười"),
    ("Studio ánh sáng neon",
     "Studio chụp ảnh tối với đèn neon dạng ống màu hồng và xanh dọc tường, sàn bê tông bóng phản chiếu, khói mỏng, khối hộp vuông làm bục ngồi.",
     "Studio thời trang", ["Y2K", "Streetwear"],
     "bộ đồ bó vinyl đen một mảnh khoét hông, boots cao đùi, khuyên vòng to",
     "ngồi trên khối hộp vắt chân dài, tựa ống neon nghiêng đầu, đứng chữ S tay vuốt tóc, ngồi xổm nhìn thẳng ống kính",
     "áo lưới đen mỏng, quần da đen, xích bạc, nhẫn bạc",
     "ngồi trên khối hộp chống khuỷu tay, tựa ống neon cúi đầu, đứng chân rộng kéo cổ áo, ngồi xổm nhìn thẳng ống kính"),
    ("Thư viện cổ điển",
     "Thư viện cổ kiểu châu Âu: kệ sách gỗ cao chạm trần, thang trượt gỗ, ghế bành da nâu, đèn bàn chao xanh, cửa sổ vòm có nắng chiếu xiên, sàn gỗ.",
     "Vintage", ["Old money", "Tối giản"],
     "sơ mi lụa trắng buộc vạt + chân váy bút chì xẻ, kính gọng mảnh, giày cao gót",
     "ngồi trên thang trượt vắt chân, tựa kệ sách cầm sách, ngồi ghế bành gác chân lên tay ghế, đứng dưới nắng cửa sổ tháo kính",
     "gile len không áo trong khoe tay, quần âu xám, kính gọng tròn",
     "ngồi trên thang trượt cầm sách, tựa kệ sách khoanh tay, ngồi ghế bành vắt chân, đứng dưới nắng cửa sổ tháo kính"),
    ("Đường đua xe cổ ven biển",
     "Con đường ven biển uốn lượn trên vách đá: xe mui trần cổ màu đỏ đỗ bên lề, lan can đá trắng, biển xanh thẳm phía dưới, núi xa, nắng chiều.",
     "Du lịch", ["Old money", "Âu Mỹ"],
     "đầm hai dây chấm bi trắng đen ôm, khăn lụa buộc tóc, kính râm mắt mèo",
     "ngồi trên nắp capo xe vắt chân, tựa cửa xe giữ khăn, ngồi trong xe gác tay lên cửa, đứng bên lan can đá vén tóc",
     "áo polo trắng mở cúc, quần âu kem, kính râm phi công, đồng hồ",
     "ngồi trên nắp capo xe, tựa cửa xe khoanh tay, ngồi trong xe gác tay lên cửa, đứng bên lan can đá cởi kính"),
    ("Khu vườn nhiệt đới có nhà kính",
     "Nhà kính vòm khung sắt trắng đầy cây nhiệt đới: lá monstera khổng lồ, cây cọ, ghế mây hình quạt, đài phun nước nhỏ, ánh nắng lốm đốm qua kính.",
     "Hồ bơi / resort", ["Boho", "Clean girl"],
     "bộ đồ lụa xanh lá áo cổ yếm hở lưng + quần ống rộng, hoa tai vàng",
     "ngồi ghế mây hình quạt vắt chân, đứng giữa lá monstera vén tóc, tựa đài phun nước, ngoái lại khoe lưng trần",
     "sơ mi lụa họa tiết lá mở ngực, quần âu trắng, nhẫn vàng",
     "ngồi ghế mây hình quạt dang chân, đứng giữa lá monstera vén lá, tựa đài phun nước, đứng nghiêng chỉnh cổ áo"),
    ("Sân bóng rổ đường phố",
     "Sân bóng rổ đường phố lúc chiều: rổ lưới xích, sàn sơn xanh đỏ có vạch trắng, lưới thép rào quanh, tường graffiti màu (không chữ đọc được), toà nhà phía sau.",
     "Thể thao", ["Sporty", "Streetwear"],
     "áo bra thể thao + quần biker short, áo jersey oversize trễ vai, sneaker trắng cổ cao",
     "ngồi trên quả bóng vắt chân, tựa lưới thép móc tay, đứng ôm bóng nghiêng hông, ngồi bậc khán đài chống cằm",
     "áo ba lỗ bóng rổ khoe cơ tay, quần short, băng đô, sneaker",
     "xoay bóng trên ngón tay, tựa lưới thép móc tay, ngồi trên bóng chống khuỷu tay, ngồi bậc khán đài vắt khăn lên vai"),
    ("Cửa hàng hoa góc phố",
     "Cửa hàng hoa góc phố châu Âu: mặt tiền gỗ sơn xanh, xô hoa tươi nhiều màu bày trên vỉa hè, xe đạp có giỏ hoa, đường lát đá, nắng sáng dịu.",
     "Cà phê", ["Hàn Quốc", "Nàng thơ"],
     "đầm hoa nhí cổ vuông ôm eo, cardigan mỏng, giày búp bê",
     "ôm bó hoa ngửi hoa, ngồi trên bậc cửa tiệm, dắt xe đạp giỏ hoa, ngồi xổm chọn hoa nhìn lên",
     "sơ mi kẻ sọc xanh xắn tay, quần chinos be, tạp dề vải, đồng hồ",
     "ôm bó hoa nhìn xuống cười, tựa khung cửa tiệm, dắt xe đạp giỏ hoa, ngồi trên bậc cửa cầm hoa"),
]
FEMALE_FACES = {
    "Châu Á": ["cô gái Việt", "cô gái Hàn Quốc", "cô gái Nhật", "cô gái Thái", "tiểu thư Trung Quốc", "cô gái Philippines lai"],
    "Châu Âu": ["cô gái Pháp", "cô gái Ý", "cô gái Nga", "cô gái Bắc Âu tóc vàng", "cô gái Tây Ban Nha"],
    "Mỹ La-tinh": ["mỹ nhân Brazil", "cô gái Colombia", "cô gái Mexico", "cô gái Argentina"],
    "Châu Phi": ["người mẫu Ethiopia", "người mẫu Nigeria da nâu sẫm"],
    "Trung Đông": ["cô gái Li-băng", "cô gái Ba Tư"],
}
MALE_FACES = {
    "Châu Á": ["nam Việt Nam", "nam Hàn Quốc", "nam Nhật", "nam Thái", "nam Trung Quốc"],
    "Châu Âu": ["nam Ý", "nam Pháp", "nam Tây Ban Nha", "nam Anh", "nam Bắc Âu"],
    "Mỹ La-tinh": ["nam Brazil", "nam Argentina"],
    "Châu Phi": ["nam người mẫu da đen cao lớn"],
    "Trung Đông": ["nam Thổ Nhĩ Kỳ", "nam Li-băng"],
}
HAIRS = ["Dài uốn sóng", "Dài thẳng", "Ngang vai", "Bob ngắn", "Đuôi ngựa", "Búi cao", "Tết tóc", "Mái thưa"]
MAKEUPS = ["Trong veo tự nhiên", "Hàn Quốc má hồng", "Douyin sắc nét", "Âu Mỹ đậm", "Môi đỏ cổ điển"]
F_BODIES = ["Mảnh mai", "Cao chân dài", "Đầy đặn quyến rũ", "Săn chắc thể thao"]
M_BODIES = ["Cao chân dài", "Săn chắc thể thao"]
M_HAIRS = ["tóc vuốt ngược", "tóc rủ có texture", "tóc undercut", "tóc xoăn nhẹ", "tóc ngắn gọn", "tóc dài buộc nửa"]
F_AGES, M_AGES = ["21–24", "22–25", "23–27"], ["23–27", "24–28", "25–30"]
HOT = ["Gợi cảm", "Quyến rũ", "Nóng bỏng"]


def _pick(pool: list, used: set, rnd: random.Random):
    fresh = [x for x in pool if x not in used] or pool
    x = rnd.choice(fresh)
    used.add(x)
    return x


def make_item(theme: tuple, male: bool, sexy: str, used: dict, rnd: random.Random) -> dict:
    """1 video: chủ đề + người mẫu mới (nét người/gu/tóc không trùng các video khác trong lô)."""
    name, desc, style, aes, f_out, f_pose, m_out, m_pose = theme
    faces = MALE_FACES if male else FEMALE_FACES
    region = _pick([r for r in faces for _ in faces[r]], used.setdefault("region", set()), rnd)
    face = _pick(faces[region], used.setdefault("face", set()), rnd)
    item = {"theme": name, "gender": "Nam" if male else "Nữ", "region": region,
            "age": rnd.choice(M_AGES if male else F_AGES), "aesthetic": ", ".join(aes),
            "body": _pick(M_BODIES if male else F_BODIES, used.setdefault("body" + str(male), set()), rnd),
            "sexy": sexy if sexy in HOT + ["Kín đáo", "Vừa phải"] else rnd.choice(HOT), "style": style,
            "location": {"name": name, "description": desc + " Vắng, không người."}}
    if male:
        item.update(hair="", makeup="", notes=f"{face} điển trai, {_pick(M_HAIRS, used.setdefault('mhair', set()), rnd)}, {m_out}",
                    pose_notes=f"dáng nam quyến rũ: {m_pose}")
    else:
        item.update(hair=_pick(HAIRS, used.setdefault("hair", set()), rnd),
                    makeup=_pick(MAKEUPS, used.setdefault("makeup", set()), rnd),
                    notes=f"{face} xinh đẹp cuốn hút, {f_out}", pose_notes=f"dáng nữ gợi cảm cuốn hút: {f_pose}")
    item["title"] = f"{name}{' (nam)' if male else ''}"
    return item


def plan(n: int, gender: str = "mix", sexy: str = "auto", avoid: set | None = None, seed: int | None = None,
         notes: str = "") -> list[dict]:
    """n video, mỗi video 1 chủ đề + 1 người mẫu khác nhau. gender: mix (xen kẽ ~60% nữ) / nu / nam.
    avoid: tên bối cảnh đã dùng ở lô trước — chỉ dùng lại khi hết chủ đề mới."""
    rnd = random.Random(seed)
    fresh = [t for t in THEMES if t[0] not in (avoid or set())]
    old = [t for t in THEMES if t not in fresh]
    rnd.shuffle(fresh), rnd.shuffle(old)
    themes = (fresh + old) * (n // len(THEMES) + 1)
    used: dict = {}
    out = []
    for i in range(n):
        male = gender == "nam" or (gender == "mix" and i % 5 in (1, 3))
        it = make_item(themes[i], male, sexy, used, rnd)
        if notes:
            it["notes"] += f"; {notes}"
        out.append(it)
    return out


def reroll(items: list[dict], idx: int, avoid: set | None = None, seed: int | None = None) -> dict:
    """Đổi 1 video sang chủ đề + người mẫu khác, không trùng các video còn lại trong lô."""
    rnd = random.Random(seed)
    others = [x for i, x in enumerate(items) if i != idx]
    taken = {x["theme"] for x in others}
    pool = [t for t in THEMES if t[0] not in taken and t[0] not in (avoid or set()) and t[0] != items[idx]["theme"]] \
        or [t for t in THEMES if t[0] not in taken] or THEMES
    used: dict = {"face": {x["notes"].split(" xinh")[0].split(" điển")[0] for x in others},
                  "region": set(), "hair": {x["hair"] for x in others}, "makeup": {x["makeup"] for x in others}}
    cur = items[idx]
    return make_item(rnd.choice(pool), cur["gender"] == "Nam", cur["sexy"], used, rnd)

# tên bối cảnh ở các kế hoạch tay trước đây (output/plans/pose_ads_*.json) -> chủ đề tương ứng trong THEMES
ALIASES = {
    "Bãi biển Đà Nẵng nắng chiều": "Bãi biển nhiệt đới nắng chiều",
    "Hẻm phố đêm Seoul neon": "Hẻm phố đêm neon sau mưa",
    "Bến du thuyền Monaco": "Bến du thuyền sang trọng",
    "Phố mua sắm cao cấp Thượng Hải": "Phố mua sắm cao cấp",
    "Đồi cỏ lau Đà Lạt lúc chiều": "Đồi cỏ lau lúc chiều",
    "Phố cổ Hội An tường vàng": "Phố cổ tường vàng đèn lồng",
    "Villa giữa rừng nhiệt đới Bali": "Villa giữa rừng nhiệt đới",
    "Cầu gỗ villa trên mặt nước Maldives": "Cầu gỗ villa trên mặt nước",
    "Sân thượng Brooklyn và cầu thang thoát hiểm": "Sân thượng gạch đỏ New York",
}
